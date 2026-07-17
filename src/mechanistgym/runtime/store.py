"""SQLite persistence for tasks, artifacts, checkpoints, and execution traces."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from .types import Artifact, Checkpoint, EventType, RuntimeEvent, Task, TaskStatus


class RuntimeStoreError(RuntimeError):
    """Base exception for persistence and integrity failures."""


class TaskDefinitionMismatch(RuntimeStoreError):
    """A task identifier was reused with a different immutable definition."""


class CheckpointConflict(RuntimeStoreError):
    """The persisted checkpoint advanced before the proposed commit."""


class CorruptStoreError(RuntimeStoreError):
    """Persisted data failed a checkpoint or checksum invariant."""


@runtime_checkable
class RuntimeStore(Protocol):
    """Persistence contract required by :class:`DurableRunner`."""

    def ensure_task(self, task: Task) -> Checkpoint:
        """Create ``task`` once or validate its existing definition."""

    def get_status(self, task_id: str) -> TaskStatus:
        """Return the persisted lifecycle state."""

    def transition_status(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        event_type: EventType,
        detail: str,
        step_index: int | None = None,
        agent_name: str | None = None,
    ) -> None:
        """Atomically persist a legal state transition and trace event."""

    def load_checkpoint(self, task_id: str) -> Checkpoint:
        """Load and integrity-check the latest checkpoint."""

    def list_artifacts(self, task_id: str) -> tuple[Artifact, ...]:
        """Return committed artifacts ordered by task step."""

    def commit_step(
        self,
        *,
        artifact: Artifact,
        expected_checkpoint: Checkpoint,
        new_checkpoint: Checkpoint,
    ) -> None:
        """Atomically commit one artifact and the checkpoint that references it."""

    def append_event(
        self,
        task_id: str,
        event_type: EventType,
        *,
        step_index: int | None = None,
        agent_name: str | None = None,
        detail: str = "",
    ) -> None:
        """Append one immutable execution event."""

    def list_events(self, task_id: str) -> tuple[RuntimeEvent, ...]:
        """Return the ordered execution trace."""


_ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset({TaskStatus.RUNNING, TaskStatus.FAILED}),
    TaskStatus.RUNNING: frozenset({TaskStatus.RECOVERING, TaskStatus.SUCCEEDED, TaskStatus.FAILED}),
    TaskStatus.RECOVERING: frozenset({TaskStatus.RUNNING, TaskStatus.SUCCEEDED, TaskStatus.FAILED}),
    TaskStatus.FAILED: frozenset({TaskStatus.RECOVERING}),
    TaskStatus.SUCCEEDED: frozenset(),
}

_TRANSITION_EVENTS: dict[tuple[TaskStatus, TaskStatus], EventType] = {
    (TaskStatus.PENDING, TaskStatus.RUNNING): EventType.TASK_STARTED,
    (TaskStatus.PENDING, TaskStatus.FAILED): EventType.TASK_FAILED,
    (TaskStatus.RUNNING, TaskStatus.RECOVERING): EventType.STEP_REROUTED,
    (TaskStatus.RUNNING, TaskStatus.SUCCEEDED): EventType.TASK_COMPLETED,
    (TaskStatus.RUNNING, TaskStatus.FAILED): EventType.TASK_FAILED,
    (TaskStatus.RECOVERING, TaskStatus.RUNNING): EventType.RECOVERY_COMPLETED,
    (TaskStatus.RECOVERING, TaskStatus.SUCCEEDED): EventType.TASK_COMPLETED,
    (TaskStatus.RECOVERING, TaskStatus.FAILED): EventType.TASK_FAILED,
    (TaskStatus.FAILED, TaskStatus.RECOVERING): EventType.TASK_RESUMED,
}


class SQLiteRuntimeStore:
    """Local durable store with atomic artifact-checkpoint commits."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._initialize_schema()

    def __enter__(self) -> SQLiteRuntimeStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying SQLite connection."""

        self._connection.close()

    def _initialize_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    objective TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    status TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    step_index INTEGER NOT NULL,
                    producer TEXT NOT NULL,
                    content TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    UNIQUE(task_id, step_index)
                );

                CREATE TABLE IF NOT EXISTS checkpoints (
                    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
                    next_step INTEGER NOT NULL,
                    artifact_ids_json TEXT NOT NULL,
                    revision INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    event_type TEXT NOT NULL,
                    step_index INTEGER,
                    agent_name TEXT,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _steps_json(steps: Sequence[str]) -> str:
        return json.dumps(list(steps), ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def _append_event(
        self,
        task_id: str,
        event_type: EventType,
        *,
        step_index: int | None = None,
        agent_name: str | None = None,
        detail: str = "",
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO events (
                task_id, event_type, step_index, agent_name, detail, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                event_type.value,
                step_index,
                agent_name,
                detail,
                self._now(),
            ),
        )

    def ensure_task(self, task: Task) -> Checkpoint:
        """Create an initial checkpoint or reject a changed definition."""

        checkpoint = Checkpoint(task_id=task.task_id)
        steps_json = self._steps_json(task.steps)
        with self._connection:
            inserted = self._connection.execute(
                """
                INSERT OR IGNORE INTO tasks (task_id, objective, steps_json, status)
                VALUES (?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.objective,
                    steps_json,
                    TaskStatus.PENDING.value,
                ),
            )
            if inserted.rowcount == 1:
                self._connection.execute(
                    """
                    INSERT INTO checkpoints (task_id, next_step, artifact_ids_json, revision)
                    VALUES (?, ?, ?, ?)
                    """,
                    (task.task_id, 0, "[]", 0),
                )
                self._append_event(
                    task.task_id,
                    EventType.TASK_CREATED,
                    detail=f"created task with {len(task.steps)} steps",
                )
                return checkpoint

            row = self._connection.execute(
                "SELECT objective, steps_json FROM tasks WHERE task_id = ?",
                (task.task_id,),
            ).fetchone()
            if row is None:
                raise RuntimeStoreError("task creation lost a concurrent insert")
            try:
                expected_steps = tuple(json.loads(row["steps_json"]))
            except (json.JSONDecodeError, TypeError) as exc:
                raise CorruptStoreError("invalid persisted task definition") from exc
            if row["objective"] != task.objective or expected_steps != task.steps:
                raise TaskDefinitionMismatch(
                    f"task_id {task.task_id!r} already has a different definition"
                )
        return self.load_checkpoint(task.task_id)

    def get_status(self, task_id: str) -> TaskStatus:
        row = self._connection.execute(
            "SELECT status FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise RuntimeStoreError(f"unknown task_id {task_id!r}")
        try:
            return TaskStatus(row["status"])
        except ValueError as exc:
            raise CorruptStoreError(f"unknown persisted task status {row['status']!r}") from exc

    def transition_status(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        event_type: EventType,
        detail: str,
        step_index: int | None = None,
        agent_name: str | None = None,
    ) -> None:
        """Persist a compare-and-swap state transition and its trace event."""

        current = self.get_status(task_id)
        if status not in _ALLOWED_TRANSITIONS[current]:
            raise RuntimeStoreError(f"illegal task transition: {current.value} -> {status.value}")
        expected_event = _TRANSITION_EVENTS[(current, status)]
        if event_type is not expected_event:
            raise RuntimeStoreError(
                f"transition {current.value} -> {status.value} requires {expected_event.value}"
            )
        with self._connection:
            updated = self._connection.execute(
                "UPDATE tasks SET status = ? WHERE task_id = ? AND status = ?",
                (status.value, task_id, current.value),
            )
            if updated.rowcount != 1:
                raise RuntimeStoreError("task status changed concurrently")
            if status is TaskStatus.SUCCEEDED:
                completion = self._connection.execute(
                    """
                    SELECT tasks.steps_json, checkpoints.next_step
                    FROM tasks
                    JOIN checkpoints USING (task_id)
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
                if completion is None:
                    raise RuntimeStoreError("task is missing its completion checkpoint")
                try:
                    step_count = len(json.loads(completion["steps_json"]))
                except (json.JSONDecodeError, TypeError) as exc:
                    raise CorruptStoreError("invalid persisted task steps") from exc
                if completion["next_step"] != step_count:
                    raise RuntimeStoreError(
                        "task cannot succeed before every configured step is committed"
                    )
            self._append_event(
                task_id,
                event_type,
                step_index=step_index,
                agent_name=agent_name,
                detail=detail,
            )

    def load_checkpoint(self, task_id: str) -> Checkpoint:
        row = self._connection.execute(
            """
            SELECT next_step, artifact_ids_json, revision
            FROM checkpoints
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()
        if row is None:
            raise RuntimeStoreError(f"no checkpoint found for task_id {task_id!r}")

        try:
            raw_artifact_ids = json.loads(row["artifact_ids_json"])
            if not isinstance(raw_artifact_ids, list) or not all(
                isinstance(item, str) for item in raw_artifact_ids
            ):
                raise ValueError("artifact_ids_json is not a list of strings")
            checkpoint = Checkpoint(
                task_id=task_id,
                next_step=row["next_step"],
                artifact_ids=tuple(raw_artifact_ids),
                revision=row["revision"],
            )
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise CorruptStoreError(f"invalid checkpoint for task_id {task_id!r}") from exc

        artifacts = self.list_artifacts(task_id)
        committed_ids = tuple(artifact.artifact_id for artifact in artifacts)
        if committed_ids != checkpoint.artifact_ids:
            raise CorruptStoreError(
                "checkpoint artifact references do not match committed artifacts"
            )
        return checkpoint

    @staticmethod
    def _artifact_from_row(row: sqlite3.Row) -> Artifact:
        try:
            return Artifact(
                artifact_id=row["artifact_id"],
                task_id=row["task_id"],
                step_index=row["step_index"],
                producer=row["producer"],
                content=row["content"],
                media_type=row["media_type"],
                checksum=row["checksum"],
            )
        except (TypeError, ValueError) as exc:
            raise CorruptStoreError(f"invalid persisted artifact {row['artifact_id']!r}") from exc

    def list_artifacts(self, task_id: str) -> tuple[Artifact, ...]:
        rows = self._connection.execute(
            """
            SELECT artifact_id, task_id, step_index, producer, content, media_type, checksum
            FROM artifacts
            WHERE task_id = ?
            ORDER BY step_index
            """,
            (task_id,),
        ).fetchall()
        return tuple(self._artifact_from_row(row) for row in rows)

    def commit_step(
        self,
        *,
        artifact: Artifact,
        expected_checkpoint: Checkpoint,
        new_checkpoint: Checkpoint,
    ) -> None:
        """Commit an artifact and checkpoint in one SQLite transaction."""

        if new_checkpoint != expected_checkpoint.advance(artifact):
            raise ValueError("new_checkpoint is not the valid successor checkpoint")

        try:
            with self._connection:
                status_guard = self._connection.execute(
                    """
                    UPDATE tasks
                    SET status = status
                    WHERE task_id = ? AND status IN (?, ?)
                    """,
                    (
                        artifact.task_id,
                        TaskStatus.RUNNING.value,
                        TaskStatus.RECOVERING.value,
                    ),
                )
                if status_guard.rowcount != 1:
                    raise RuntimeStoreError(
                        "artifacts may only commit while a task is running or recovering"
                    )

                task_row = self._connection.execute(
                    "SELECT steps_json FROM tasks WHERE task_id = ?",
                    (artifact.task_id,),
                ).fetchone()
                if task_row is None:
                    raise RuntimeStoreError(f"unknown task_id {artifact.task_id!r}")
                try:
                    step_count = len(json.loads(task_row["steps_json"]))
                except (json.JSONDecodeError, TypeError) as exc:
                    raise CorruptStoreError("invalid persisted task steps") from exc
                if expected_checkpoint.next_step >= step_count:
                    raise RuntimeStoreError("cannot commit an artifact past the final task step")

                row = self._connection.execute(
                    """
                    SELECT next_step, artifact_ids_json, revision
                    FROM checkpoints
                    WHERE task_id = ?
                    """,
                    (artifact.task_id,),
                ).fetchone()
                if row is None:
                    raise RuntimeStoreError(f"unknown task_id {artifact.task_id!r}")
                try:
                    persisted_artifact_ids = tuple(json.loads(row["artifact_ids_json"]))
                except (json.JSONDecodeError, TypeError) as exc:
                    raise CorruptStoreError("invalid persisted checkpoint artifacts") from exc
                persisted_signature = (
                    row["next_step"],
                    persisted_artifact_ids,
                    row["revision"],
                )
                proposed_signature = (
                    expected_checkpoint.next_step,
                    expected_checkpoint.artifact_ids,
                    expected_checkpoint.revision,
                )
                if persisted_signature != proposed_signature:
                    raise CheckpointConflict("checkpoint advanced before this step could commit")

                try:
                    self._connection.execute(
                        """
                        INSERT INTO artifacts (
                            artifact_id, task_id, step_index, producer,
                            content, media_type, checksum
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            artifact.artifact_id,
                            artifact.task_id,
                            artifact.step_index,
                            artifact.producer,
                            artifact.content,
                            artifact.media_type,
                            artifact.checksum,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise CheckpointConflict("artifact step was already committed") from exc

                updated = self._connection.execute(
                    """
                    UPDATE checkpoints
                    SET next_step = ?, artifact_ids_json = ?, revision = ?
                    WHERE task_id = ? AND revision = ?
                    """,
                    (
                        new_checkpoint.next_step,
                        json.dumps(list(new_checkpoint.artifact_ids), separators=(",", ":")),
                        new_checkpoint.revision,
                        artifact.task_id,
                        expected_checkpoint.revision,
                    ),
                )
                if updated.rowcount != 1:
                    raise CheckpointConflict("checkpoint revision changed during commit")

                self._append_event(
                    artifact.task_id,
                    EventType.ARTIFACT_COMMITTED,
                    step_index=artifact.step_index,
                    agent_name=artifact.producer,
                    detail=f"committed {artifact.artifact_id}",
                )
                self._append_event(
                    artifact.task_id,
                    EventType.CHECKPOINT_SAVED,
                    step_index=new_checkpoint.next_step,
                    agent_name=artifact.producer,
                    detail=f"saved revision {new_checkpoint.revision}",
                )
        except (CheckpointConflict, CorruptStoreError, RuntimeStoreError):
            raise
        except sqlite3.DatabaseError as exc:
            raise RuntimeStoreError("SQLite could not atomically commit the step") from exc

    def append_event(
        self,
        task_id: str,
        event_type: EventType,
        *,
        step_index: int | None = None,
        agent_name: str | None = None,
        detail: str = "",
    ) -> None:
        with self._connection:
            self._append_event(
                task_id,
                event_type,
                step_index=step_index,
                agent_name=agent_name,
                detail=detail,
            )

    def list_events(self, task_id: str) -> tuple[RuntimeEvent, ...]:
        rows = self._connection.execute(
            """
            SELECT sequence, task_id, event_type, step_index, agent_name, detail, created_at
            FROM events
            WHERE task_id = ?
            ORDER BY sequence
            """,
            (task_id,),
        ).fetchall()
        try:
            return tuple(
                RuntimeEvent(
                    sequence=row["sequence"],
                    task_id=row["task_id"],
                    event_type=EventType(row["event_type"]),
                    step_index=row["step_index"],
                    agent_name=row["agent_name"],
                    detail=row["detail"],
                    created_at=row["created_at"],
                )
                for row in rows
            )
        except (TypeError, ValueError) as exc:
            raise CorruptStoreError(f"invalid event trace for task_id {task_id!r}") from exc
