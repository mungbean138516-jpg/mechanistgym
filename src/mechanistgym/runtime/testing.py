"""Deterministic adapters for recovery tests and demonstrations."""

from __future__ import annotations

from dataclasses import dataclass, field

from .adapters import RecoverableAgentError
from .types import Artifact, Task


@dataclass
class ScriptedAgentAdapter:
    """Produce deterministic artifacts and fail on configured task steps."""

    name: str
    fail_on_steps: frozenset[int] = frozenset()
    calls: list[int] = field(default_factory=list, init=False)

    async def execute_step(
        self,
        task: Task,
        *,
        step_index: int,
        artifacts: tuple[Artifact, ...],
    ) -> Artifact:
        """Record the call, inject a failure, or return reproducible content."""

        if len(artifacts) != step_index:
            raise ValueError("adapter received a non-contiguous artifact history")
        self.calls.append(step_index)
        if step_index in self.fail_on_steps:
            raise RecoverableAgentError(f"injected failure at step {step_index}")
        return Artifact.create(
            task_id=task.task_id,
            step_index=step_index,
            producer=self.name,
            content=f"completed:{task.steps[step_index]}",
        )
