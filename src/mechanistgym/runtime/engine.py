"""Sequential async runner with checkpointed failover between agent adapters."""

from __future__ import annotations

from collections.abc import Sequence

from .adapters import AgentAdapter, InvalidAgentOutput, RecoverableAgentError
from .store import RuntimeStore, RuntimeStoreError
from .types import Artifact, EventType, ExecutionResult, Task, TaskStatus


class ExecutionFailed(RuntimeError):
    """Raised after all available agents fail the current resumable step."""

    def __init__(self, result: ExecutionResult) -> None:
        super().__init__(
            f"task {result.task.task_id!r} failed at step {result.checkpoint.next_step}"
        )
        self.result = result


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
    def _validate_failover_chain(failover_chain: Sequence[AgentAdapter]) -> None:
        if not failover_chain:
            raise ValueError("at least one AgentAdapter is required")
        names = [adapter.name for adapter in failover_chain]
        if any(not name.strip() for name in names):
            raise ValueError("adapter names must not be empty")
        if len(names) != len(set(names)):
            raise ValueError("adapter names must be unique within one run")

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
        failover_chain: Sequence[AgentAdapter],
    ) -> ExecutionResult:
        """Run or resume ``task`` using adapters in ordered failover priority."""

        self._validate_failover_chain(failover_chain)
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
            adapter = failover_chain[active_adapter]
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
                if active_adapter + 1 >= len(failover_chain):
                    self.store.transition_status(
                        task.task_id,
                        TaskStatus.FAILED,
                        event_type=EventType.TASK_FAILED,
                        detail=f"no fallback remained for step {step_index}",
                    )
                    raise ExecutionFailed(self._result(task)) from exc

                fallback = failover_chain[active_adapter + 1]
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
