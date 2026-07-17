"""User-facing demonstration of checkpointed agent failover."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .engine import DurableRunner
from .store import SQLiteRuntimeStore
from .testing import ScriptedAgentAdapter
from .types import Task


async def run_checkpoint_failover_demo_async(database_path: str | Path) -> dict[str, Any]:
    """Fail one worker after a checkpoint and finish with a fallback worker."""

    task = Task(
        task_id="decay-report",
        objective="Prepare a reproducible parameter-estimation report.",
        steps=(
            "validate decay observations",
            "estimate the decay parameter",
            "write the verification report",
        ),
    )
    primary = ScriptedAgentAdapter(name="primary-agent", fail_on_steps=frozenset({1}))
    fallback = ScriptedAgentAdapter(name="fallback-agent")
    with SQLiteRuntimeStore(database_path) as store:
        result = await DurableRunner(store).run(task, (primary, fallback))

    return {
        "task_id": task.task_id,
        "status": result.status.value,
        "checkpoint_revision": result.checkpoint.revision,
        "recovered": result.recovered,
        "failure_count": result.failure_count,
        "primary_calls": primary.calls,
        "fallback_calls": fallback.calls,
        "artifacts": [
            {
                "step": artifact.step_index,
                "producer": artifact.producer,
                "content": artifact.content,
                "checksum": artifact.checksum,
            }
            for artifact in result.artifacts
        ],
        "events": [event.event_type.value for event in result.events],
    }


def run_checkpoint_failover_demo(database_path: str | Path | None = None) -> dict[str, Any]:
    """Run the async failover demonstration from synchronous code."""

    if database_path is not None:
        return asyncio.run(run_checkpoint_failover_demo_async(database_path))
    with TemporaryDirectory() as directory:
        path = Path(directory) / "runtime.sqlite3"
        return asyncio.run(run_checkpoint_failover_demo_async(path))


def main() -> None:
    """Print a structured recovery trace."""

    print(json.dumps(run_checkpoint_failover_demo(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
