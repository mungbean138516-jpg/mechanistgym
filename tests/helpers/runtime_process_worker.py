"""Child process used to verify recovery after an abrupt interpreter exit."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from mechanistgym.runtime import Artifact, DurableRunner, SQLiteRuntimeStore, Task

PROCESS_TASK = Task(
    task_id="process-recovery",
    objective="verify recovery across an abrupt process exit",
    steps=("prepare", "analyze", "report"),
)


class AbruptExitAdapter:
    """Commit step zero, then terminate the interpreter during step one."""

    name = "process-primary"

    async def execute_step(
        self,
        task: Task,
        *,
        step_index: int,
        artifacts: tuple[Artifact, ...],
    ) -> Artifact:
        if len(artifacts) != step_index:
            raise AssertionError("worker did not receive the committed artifact prefix")
        if step_index == 1:
            os._exit(17)
        return Artifact.create(
            task_id=task.task_id,
            step_index=step_index,
            producer=self.name,
            content=f"primary completed {task.steps[step_index]}",
        )


class ResumeAdapter:
    """Finish every uncommitted step after the new process opens the store."""

    name = "process-fallback"

    async def execute_step(
        self,
        task: Task,
        *,
        step_index: int,
        artifacts: tuple[Artifact, ...],
    ) -> Artifact:
        if len(artifacts) != step_index:
            raise AssertionError("recovery did not receive the committed artifact prefix")
        return Artifact.create(
            task_id=task.task_id,
            step_index=step_index,
            producer=self.name,
            content=f"fallback completed {task.steps[step_index]}",
        )


async def run_worker(mode: str, database: Path) -> None:
    """Run either the deliberately crashing worker or the recovery worker."""

    adapter = AbruptExitAdapter() if mode == "crash" else ResumeAdapter()
    with SQLiteRuntimeStore(database) as store:
        await DurableRunner(store).run(PROCESS_TASK, (adapter,))


def main() -> None:
    """Parse the child-process mode and execute it."""

    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("crash", "resume"))
    parser.add_argument("database", type=Path)
    arguments = parser.parse_args()
    asyncio.run(run_worker(arguments.mode, arguments.database))


if __name__ == "__main__":
    main()
