"""User-facing demonstration of bounded concurrency and isolated recovery."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .adapters import RecoverableAgentError
from .engine import DurableRunner, ExecutionSpec
from .store import SQLiteRuntimeStore
from .types import Artifact, Task


class DemoPrimaryAdapter:
    """Create deterministic overlap and fail one Task after its first commit."""

    name = "batch-primary"

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.active = 0
        self.max_active = 0
        self.first_step_entries = 0
        self.first_pair_ready = asyncio.Event()

    async def execute_step(
        self,
        task: Task,
        *,
        step_index: int,
        artifacts: tuple[Artifact, ...],
    ) -> Artifact:
        if len(artifacts) != step_index:
            raise ValueError("adapter received a non-contiguous Artifact prefix")
        self.calls.append((task.task_id, step_index))

        if step_index == 0:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.first_step_entries += 1
            if self.first_step_entries >= 2:
                self.first_pair_ready.set()
            try:
                await self.first_pair_ready.wait()
                await asyncio.sleep(0)
            finally:
                self.active -= 1

        if task.task_id == "batch-b" and step_index == 1:
            raise RecoverableAgentError("injected failure for batch-b")

        return Artifact.create(
            task_id=task.task_id,
            step_index=step_index,
            producer=self.name,
            content=f"primary completed {task.steps[step_index]}",
        )


class DemoFallbackAdapter:
    """Complete the one step deliberately failed by the primary adapter."""

    name = "batch-fallback"

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def execute_step(
        self,
        task: Task,
        *,
        step_index: int,
        artifacts: tuple[Artifact, ...],
    ) -> Artifact:
        if len(artifacts) != step_index:
            raise ValueError("fallback received a non-contiguous Artifact prefix")
        self.calls.append((task.task_id, step_index))
        return Artifact.create(
            task_id=task.task_id,
            step_index=step_index,
            producer=self.name,
            content=f"fallback completed {task.steps[step_index]}",
        )


async def run_bounded_async_demo_async(database_path: str | Path) -> dict[str, Any]:
    """Run three Tasks with two active slots in a new or empty database file."""

    database_path = Path(database_path)
    if database_path.exists() and database_path.stat().st_size:
        raise ValueError("the async demo requires a new or empty database path")

    tasks = tuple(
        Task(
            task_id=task_id,
            objective=f"complete {task_id}",
            steps=("prepare", "report"),
        )
        for task_id in ("batch-a", "batch-b", "batch-c")
    )
    primary = DemoPrimaryAdapter()
    fallback = DemoFallbackAdapter()
    with SQLiteRuntimeStore(database_path) as store:
        results = await DurableRunner(store).run_many(
            tuple(ExecutionSpec(task, (primary, fallback)) for task in tasks),
            max_concurrency=2,
        )

    return {
        "max_concurrency": 2,
        "observed_max_active": primary.max_active,
        "result_order": [result.task.task_id for result in results],
        "statuses": {result.task.task_id: result.status.value for result in results},
        "recovered": {result.task.task_id: result.recovered for result in results},
        "primary_calls": sorted(primary.calls),
        "fallback_calls": sorted(fallback.calls),
    }


def run_bounded_async_demo(database_path: str | Path | None = None) -> dict[str, Any]:
    """Run the async batch demonstration from synchronous code."""

    if database_path is not None:
        return asyncio.run(run_bounded_async_demo_async(database_path))
    with TemporaryDirectory() as directory:
        path = Path(directory) / "runtime.sqlite3"
        return asyncio.run(run_bounded_async_demo_async(path))


def main() -> None:
    """Print a structured bounded-concurrency trace."""

    print(json.dumps(run_bounded_async_demo(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
