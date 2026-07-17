"""Immutable value objects for checkpointed agent execution."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum

_SAFE_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_SAFE_ARTIFACT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class TaskStatus(StrEnum):
    """Lifecycle states persisted by the local runtime."""

    PENDING = "pending"
    RUNNING = "running"
    RECOVERING = "recovering"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class EventType(StrEnum):
    """Append-only events emitted during one task execution."""

    TASK_CREATED = "task.created"
    TASK_STARTED = "task.started"
    TASK_RESUMED = "task.resumed"
    ATTEMPT_STARTED = "attempt.started"
    ARTIFACT_COMMITTED = "artifact.committed"
    CHECKPOINT_SAVED = "checkpoint.saved"
    AGENT_FAILED = "agent.failed"
    STEP_REROUTED = "step.rerouted"
    RECOVERY_COMPLETED = "recovery.completed"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"


@dataclass(frozen=True)
class Task:
    """A deterministic goal split into ordered, resumable agent steps."""

    task_id: str
    objective: str
    steps: tuple[str, ...]

    def __post_init__(self) -> None:
        if not _SAFE_TASK_ID.fullmatch(self.task_id):
            raise ValueError(
                "task_id must be 1-96 safe characters: letters, numbers, '.', '_' or '-'"
            )
        if not self.objective.strip():
            raise ValueError("objective must not be empty")
        if not self.steps:
            raise ValueError("at least one task step is required")
        if any(not step.strip() for step in self.steps):
            raise ValueError("task steps must not be empty")


@dataclass(frozen=True)
class Artifact:
    """Application-level immutable output with content-integrity checking."""

    artifact_id: str
    task_id: str
    step_index: int
    producer: str
    content: str
    media_type: str = "text/plain"
    checksum: str = ""

    def __post_init__(self) -> None:
        if not _SAFE_ARTIFACT_ID.fullmatch(self.artifact_id):
            raise ValueError("artifact_id must use safe identifier characters")
        if not _SAFE_TASK_ID.fullmatch(self.task_id):
            raise ValueError("task_id must use safe identifier characters")
        if self.step_index < 0:
            raise ValueError("step_index must be non-negative")
        if not self.producer.strip():
            raise ValueError("producer must not be empty")
        if not self.media_type.strip():
            raise ValueError("media_type must not be empty")

        expected_checksum = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        if self.checksum and self.checksum != expected_checksum:
            raise ValueError("artifact checksum does not match its content")
        if not self.checksum:
            object.__setattr__(self, "checksum", expected_checksum)

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        step_index: int,
        producer: str,
        content: str,
        media_type: str = "text/plain",
    ) -> Artifact:
        """Create the canonical one-artifact-per-step value for v0.1."""

        return cls(
            artifact_id=f"{task_id}.step-{step_index}",
            task_id=task_id,
            step_index=step_index,
            producer=producer,
            content=content,
            media_type=media_type,
        )


@dataclass(frozen=True)
class Checkpoint:
    """Serializable handoff state saved after committed agent work."""

    task_id: str
    next_step: int = 0
    artifact_ids: tuple[str, ...] = ()
    revision: int = 0

    def __post_init__(self) -> None:
        if not _SAFE_TASK_ID.fullmatch(self.task_id):
            raise ValueError("task_id must use safe identifier characters")
        if self.next_step < 0:
            raise ValueError("next_step must be non-negative")
        if self.revision < 0:
            raise ValueError("revision must be non-negative")
        if len(self.artifact_ids) != self.next_step:
            raise ValueError("checkpoint must reference exactly one artifact per completed step")
        if self.revision != self.next_step:
            raise ValueError("v0.1 checkpoint revision must equal next_step")

    def advance(self, artifact: Artifact) -> Checkpoint:
        """Return the next checkpoint after validating one new artifact."""

        if artifact.task_id != self.task_id:
            raise ValueError("artifact belongs to a different task")
        if artifact.step_index != self.next_step:
            raise ValueError("artifact step does not match checkpoint next_step")
        return Checkpoint(
            task_id=self.task_id,
            next_step=self.next_step + 1,
            artifact_ids=(*self.artifact_ids, artifact.artifact_id),
            revision=self.revision + 1,
        )


@dataclass(frozen=True)
class RuntimeEvent:
    """One persisted fact in an execution trace."""

    sequence: int
    task_id: str
    event_type: EventType
    step_index: int | None
    agent_name: str | None
    detail: str
    created_at: str


@dataclass(frozen=True)
class ExecutionResult:
    """Complete persisted state returned after success or terminal failure."""

    task: Task
    status: TaskStatus
    checkpoint: Checkpoint
    artifacts: tuple[Artifact, ...]
    events: tuple[RuntimeEvent, ...]

    @property
    def recovery_attempted(self) -> bool:
        """Return whether execution was reopened or moved to a fallback."""

        return any(
            event.event_type in {EventType.STEP_REROUTED, EventType.TASK_RESUMED}
            for event in self.events
        )

    @property
    def recovered(self) -> bool:
        """Return whether an attempted recovery ultimately succeeded."""

        return self.status is TaskStatus.SUCCEEDED and self.recovery_attempted

    @property
    def failure_count(self) -> int:
        """Return the number of recorded agent failures of any kind."""

        return sum(event.event_type is EventType.AGENT_FAILED for event in self.events)
