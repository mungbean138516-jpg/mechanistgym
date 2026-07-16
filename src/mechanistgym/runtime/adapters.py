"""Agent boundary for step-level checkpointed execution."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import Artifact, Task


class RecoverableAgentError(RuntimeError):
    """An expected worker failure that may be rerouted to another agent."""


class InvalidAgentOutput(RecoverableAgentError):
    """An agent output that violates the runtime's artifact contract."""


@runtime_checkable
class AgentAdapter(Protocol):
    """A heterogeneous agent exposed as one resumable step executor."""

    name: str

    async def execute_step(
        self,
        task: Task,
        *,
        step_index: int,
        artifacts: tuple[Artifact, ...],
    ) -> Artifact:
        """Execute only ``step_index`` using already committed artifacts."""
