"""Durable Task execution with ordered steps and bounded async batches."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import cast

from .adapters import AgentAdapter, InvalidAgentOutput, RecoverableAgentError
from .store import RuntimeStore, RuntimeStoreError
from .types import Artifact, EventType, ExecutionResult, Task, TaskStatus


def _snapshot_failover_chain(
    failover_chain: Iterable[AgentAdapter],
) -> tuple[AgentAdapter, ...]:
    """Validate and freeze one ordered adapter chain before persisted execution."""

    try:
        adapters = tuple(failover_chain)
    except TypeError as exc:
        raise TypeError("failover_chain must be an iterable of AgentAdapter values") from exc
    if not adapters:
        raise ValueError("at least one AgentAdapter is required")

    names: list[str] = []
    for adapter in adapters:
        if not isinstance(adapter, AgentAdapter) or not callable(
            getattr(adapter, "execute_step", None)
        ):
            raise TypeError("failover_chain entries must satisfy AgentAdapter")
        name = adapter.name
        if not isinstance(name, str) or not name.strip():
            raise ValueError("adapter names must be non-empty strings")
        names.append(name)
    if len(names) != len(set(names)):
        raise ValueError("adapter names must be unique within one run")
    return adapters


class ExecutionFailed(RuntimeError):
    """Raised after all available agents fail the current resumable step."""

    def __init__(self, result: ExecutionResult) -> None:
        super().__init__(
            f"task {result.task.task_id!r} failed at step {result.checkpoint.next_step}"
        )
        self.result = result


@dataclass(frozen=True)
class ExecutionSpec:
    """One durable Task and its ordered Agent failover chain."""

    task: Task
    failover_chain: tuple[AgentAdapter, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.task, Task):
            raise TypeError("task must be a Task")
        object.__setattr__(
            self,
            "failover_chain",
            _snapshot_failover_chain(self.failover_chain),
        )


class DurableRunner:
    """Execute ordered agent steps and preserve committed work across failures."""

    def __init__(self, store: RuntimeStore) -> None:
        self.store = store

    def _result(self, task: Task) -> ExecutionResult:
        events = self.store.list_events(task.task_id)
        return ExecutionResult(
            task=task,
            status=self.store.get_status(task.task_id),
            checkpoint=self.store.load_checkpoint(task.task_id),
            artifacts=self.store.list_artifacts(task.task_id),
            events=events,
        )

    @staticmethod
    def _validate_artifact(
        artifact: object,
        *,
        task: Task,
        step_index: int,
        agent_name: str,
    ) -> Artifact:
        if not isinstance(artifact, Artifact):
            raise InvalidAgentOutput("adapter did not return an Artifact")
        expected_id = f"{task.task_id}.step-{step_index}"
        if artifact.artifact_id != expected_id:
            raise InvalidAgentOutput(
                f"artifact_id must be {expected_id!r}, got {artifact.artifact_id!r}"
            )
        if artifact.task_id != task.task_id:
            raise InvalidAgentOutput("artifact belongs to a different task")
        if artifact.step_index != step_index:
            raise InvalidAgentOutput("artifact belongs to a different task step")
        if artifact.producer != agent_name:
            raise InvalidAgentOutput("artifact producer does not match the active adapter")
        return artifact

    async def run(
        self,
        task: Task,
        failover_chain: Iterable[AgentAdapter],
    ) -> ExecutionResult:
        """Run or resume ``task`` using adapters in ordered failover priority."""

        adapters = _snapshot_failover_chain(failover_chain)
        checkpoint = self.store.ensure_task(task)
        status = self.store.get_status(task.task_id)
        if checkpoint.next_step > len(task.steps):
            raise RuntimeStoreError("checkpoint points past the final task step")
        if status is TaskStatus.SUCCEEDED:
            return self._result(task)

        if status is TaskStatus.PENDING:
            self.store.transition_status(
                task.task_id,
                TaskStatus.RUNNING,
                event_type=EventType.TASK_STARTED,
                detail="started checkpointed execution",
            )
        elif status is TaskStatus.FAILED:
            self.store.transition_status(
                task.task_id,
                TaskStatus.RECOVERING,
                event_type=EventType.TASK_RESUMED,
                detail=f"resumed from checkpoint revision {checkpoint.revision}",
            )
        else:
            self.store.append_event(
                task.task_id,
                EventType.TASK_RESUMED,
                step_index=checkpoint.next_step,
                detail=f"reopened checkpoint revision {checkpoint.revision}",
            )

        active_adapter = 0
        while checkpoint.next_step < len(task.steps):
            step_index = checkpoint.next_step
            adapter = adapters[active_adapter]
            artifacts = self.store.list_artifacts(task.task_id)
            self.store.append_event(
                task.task_id,
                EventType.ATTEMPT_STARTED,
                step_index=step_index,
                agent_name=adapter.name,
                detail=f"executing step {step_index}",
            )
            try:
                candidate = await adapter.execute_step(
                    task,
                    step_index=step_index,
                    artifacts=artifacts,
                )
                artifact = self._validate_artifact(
                    candidate,
                    task=task,
                    step_index=step_index,
                    agent_name=adapter.name,
                )
            except RecoverableAgentError as exc:
                self.store.append_event(
                    task.task_id,
                    EventType.AGENT_FAILED,
                    step_index=step_index,
                    agent_name=adapter.name,
                    detail=f"{type(exc).__name__}: {exc}",
                )
                if active_adapter + 1 >= len(adapters):
                    self.store.transition_status(
                        task.task_id,
                        TaskStatus.FAILED,
                        event_type=EventType.TASK_FAILED,
                        detail=f"no fallback remained for step {step_index}",
                    )
                    raise ExecutionFailed(self._result(task)) from exc

                fallback = adapters[active_adapter + 1]
                current_status = self.store.get_status(task.task_id)
                if current_status is TaskStatus.RUNNING:
                    self.store.transition_status(
                        task.task_id,
                        TaskStatus.RECOVERING,
                        event_type=EventType.STEP_REROUTED,
                        detail=f"rerouted step {step_index}: {adapter.name} -> {fallback.name}",
                        step_index=step_index,
                        agent_name=fallback.name,
                    )
                else:
                    self.store.append_event(
                        task.task_id,
                        EventType.STEP_REROUTED,
                        step_index=step_index,
                        agent_name=fallback.name,
                        detail=f"rerouted step {step_index}: {adapter.name} -> {fallback.name}",
                    )
                active_adapter += 1
                continue
            except Exception as exc:
                self.store.append_event(
                    task.task_id,
                    EventType.AGENT_FAILED,
                    step_index=step_index,
                    agent_name=adapter.name,
                    detail=f"non-recoverable {type(exc).__name__}: {exc}",
                )
                self.store.transition_status(
                    task.task_id,
                    TaskStatus.FAILED,
                    event_type=EventType.TASK_FAILED,
                    detail=f"non-recoverable failure at step {step_index}",
                )
                raise ExecutionFailed(self._result(task)) from exc

            new_checkpoint = checkpoint.advance(artifact)
            self.store.commit_step(
                artifact=artifact,
                expected_checkpoint=checkpoint,
                new_checkpoint=new_checkpoint,
            )
            checkpoint = new_checkpoint
            if self.store.get_status(task.task_id) is TaskStatus.RECOVERING:
                self.store.transition_status(
                    task.task_id,
                    TaskStatus.RUNNING,
                    event_type=EventType.RECOVERY_COMPLETED,
                    detail=f"fallback {adapter.name} committed step {step_index}",
                    step_index=step_index,
                    agent_name=adapter.name,
                )

        self.store.transition_status(
            task.task_id,
            TaskStatus.SUCCEEDED,
            event_type=EventType.TASK_COMPLETED,
            detail=f"completed {len(task.steps)} steps",
        )
        return self._result(task)

    async def run_many(
        self,
        executions: Sequence[ExecutionSpec],
        *,
        max_concurrency: int,
    ) -> tuple[ExecutionResult, ...]:
        """Run distinct Tasks concurrently while preserving per-Task recovery semantics.

        Each Task remains sequential. ``max_concurrency`` bounds active Task workflows within this
        call. Terminal Agent failures become failed results so one Task does not cancel its
        siblings. After an infrastructure or integrity error becomes known, already-active siblings
        settle and queued Tasks do not start. If the batch is allowed to settle, one child error is
        re-raised unchanged and multiple child errors are grouped. Explicit caller cancellation
        propagates immediately and may supersede pending child errors.
        """

        if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int):
            raise TypeError("max_concurrency must be an integer")
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")

        specs = tuple(executions)
        if any(not isinstance(spec, ExecutionSpec) for spec in specs):
            raise TypeError("executions must contain only ExecutionSpec values")

        task_ids = [spec.task.task_id for spec in specs]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("task IDs must be unique within one run_many call")
        specs = tuple(ExecutionSpec(spec.task, spec.failover_chain) for spec in specs)

        if not specs:
            return ()

        semaphore = asyncio.Semaphore(max_concurrency)
        stop_queued = asyncio.Event()
        not_started = object()

        async def run_one(spec: ExecutionSpec) -> ExecutionResult | object:
            async with semaphore:
                if stop_queued.is_set():
                    return not_started
                try:
                    return await self.run(spec.task, spec.failover_chain)
                except ExecutionFailed as exc:
                    return exc.result
                except Exception:
                    stop_queued.set()
                    raise

        settled = await asyncio.gather(
            *(run_one(spec) for spec in specs),
            return_exceptions=True,
        )
        errors = [outcome for outcome in settled if isinstance(outcome, BaseException)]
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise BaseExceptionGroup("multiple batch executions failed", errors)
        if any(outcome is not_started for outcome in settled):
            raise RuntimeError("batch stopped queued Tasks without a recorded infrastructure error")
        return tuple(cast(ExecutionResult, outcome) for outcome in settled)
