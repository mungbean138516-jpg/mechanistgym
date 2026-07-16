"""Acceptance tests for checkpointed failover and close/reopen recovery."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mechanistgym.runtime import (
    Artifact,
    CheckpointConflict,
    CorruptStoreError,
    DurableRunner,
    EventType,
    ExecutionFailed,
    RuntimeStoreError,
    SQLiteRuntimeStore,
    Task,
    TaskDefinitionMismatch,
    TaskStatus,
)
from mechanistgym.runtime.demo import run_checkpoint_failover_demo_async
from mechanistgym.runtime.testing import ScriptedAgentAdapter


def _task(task_id: str = "recovery-test") -> Task:
    return Task(
        task_id=task_id,
        objective="Complete three resumable work units.",
        steps=("prepare data", "fit model", "write report"),
    )


class SimulatedProcessCrash(BaseException):
    """Escape the runner without allowing it to persist a graceful failure."""


class CrashAfterCheckpointAdapter:
    """Complete step zero, then simulate abrupt process loss on step one."""

    name = "crashing-agent"

    def __init__(self) -> None:
        self.calls: list[int] = []

    async def execute_step(
        self,
        task: Task,
        *,
        step_index: int,
        artifacts: tuple[Artifact, ...],
    ) -> Artifact:
        self.calls.append(step_index)
        if step_index == 1:
            raise SimulatedProcessCrash
        return Artifact.create(
            task_id=task.task_id,
            step_index=step_index,
            producer=self.name,
            content=f"completed:{task.steps[step_index]}",
        )


class BlockingAfterCheckpointAdapter:
    """Commit step zero and wait indefinitely during step one."""

    name = "blocking-agent"

    def __init__(self, step_started: asyncio.Event) -> None:
        self.step_started = step_started
        self.release = asyncio.Event()
        self.calls: list[int] = []

    async def execute_step(
        self,
        task: Task,
        *,
        step_index: int,
        artifacts: tuple[Artifact, ...],
    ) -> Artifact:
        del artifacts
        self.calls.append(step_index)
        if step_index == 1:
            self.step_started.set()
            await self.release.wait()
        return Artifact.create(
            task_id=task.task_id,
            step_index=step_index,
            producer=self.name,
            content=f"completed:{task.steps[step_index]}",
        )


class InvalidOutputAdapter:
    """Return a protocol-violating value for fallback coverage."""

    name = "invalid-output-agent"

    def __init__(self) -> None:
        self.calls: list[int] = []

    async def execute_step(
        self,
        task: Task,
        *,
        step_index: int,
        artifacts: tuple[Artifact, ...],
    ) -> object:
        self.calls.append(step_index)
        return object()


class BuggyAdapter:
    """Raise a non-recoverable implementation error."""

    name = "buggy-agent"

    async def execute_step(
        self,
        task: Task,
        *,
        step_index: int,
        artifacts: tuple[Artifact, ...],
    ) -> Artifact:
        raise ValueError("injected adapter bug")


class StaleReadSQLiteStore(SQLiteRuntimeStore):
    """Simulate a runner that read RUNNING before another writer completed."""

    def get_status(self, task_id: str) -> TaskStatus:
        return TaskStatus.RUNNING


class RuntimeRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_failover_uses_last_checkpoint_without_repeating_work(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            SQLiteRuntimeStore(Path(directory) / "runtime.sqlite3") as store,
        ):
            primary = ScriptedAgentAdapter(
                name="primary-agent",
                fail_on_steps=frozenset({1}),
            )
            fallback = ScriptedAgentAdapter(name="fallback-agent")

            result = await DurableRunner(store).run(_task(), (primary, fallback))

            self.assertEqual(result.status, TaskStatus.SUCCEEDED)
            self.assertTrue(result.recovered)
            self.assertEqual(result.failure_count, 1)
            self.assertEqual(result.checkpoint.next_step, 3)
            self.assertEqual(primary.calls, [0, 1])
            self.assertEqual(fallback.calls, [1, 2])
            self.assertEqual(
                [artifact.step_index for artifact in result.artifacts],
                [0, 1, 2],
            )
            self.assertEqual(
                [artifact.producer for artifact in result.artifacts],
                ["primary-agent", "fallback-agent", "fallback-agent"],
            )
            reroute = next(
                event for event in result.events if event.event_type is EventType.STEP_REROUTED
            )
            self.assertEqual(reroute.step_index, 1)
            self.assertEqual(reroute.agent_name, "fallback-agent")

    async def test_abrupt_crash_leaves_running_checkpoint_for_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "runtime.sqlite3"
            task = _task("abrupt-crash-test")
            crashing_agent = CrashAfterCheckpointAdapter()

            with SQLiteRuntimeStore(database) as first_store:
                with self.assertRaises(SimulatedProcessCrash):
                    await DurableRunner(first_store).run(task, (crashing_agent,))
                self.assertEqual(first_store.get_status(task.task_id), TaskStatus.RUNNING)
                self.assertEqual(first_store.load_checkpoint(task.task_id).next_step, 1)

            fallback = ScriptedAgentAdapter(name="fallback-agent")
            with SQLiteRuntimeStore(database) as reopened_store:
                result = await DurableRunner(reopened_store).run(task, (fallback,))

            self.assertEqual(crashing_agent.calls, [0, 1])
            self.assertEqual(fallback.calls, [1, 2])
            self.assertTrue(result.recovered)
            self.assertEqual(result.status, TaskStatus.SUCCEEDED)

    async def test_cancellation_preserves_committed_checkpoint_for_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "runtime.sqlite3"
            task = _task("cancel-recovery")
            step_started = asyncio.Event()
            blocking_agent = BlockingAfterCheckpointAdapter(step_started)

            with SQLiteRuntimeStore(database) as first_store:
                execution = asyncio.create_task(
                    DurableRunner(first_store).run(task, (blocking_agent,))
                )
                await asyncio.wait_for(step_started.wait(), timeout=5.0)
                execution.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await execution

                self.assertEqual(blocking_agent.calls, [0, 1])
                self.assertEqual(first_store.get_status(task.task_id), TaskStatus.RUNNING)
                self.assertEqual(first_store.load_checkpoint(task.task_id).next_step, 1)

            fallback = ScriptedAgentAdapter(name="cancellation-fallback")
            with SQLiteRuntimeStore(database) as reopened_store:
                result = await DurableRunner(reopened_store).run(task, (fallback,))

            self.assertEqual(result.status, TaskStatus.SUCCEEDED)
            self.assertTrue(result.recovered)
            self.assertEqual(fallback.calls, [1, 2])
            self.assertEqual([artifact.step_index for artifact in result.artifacts], [0, 1, 2])
            self.assertIn(EventType.TASK_RESUMED, [event.event_type for event in result.events])
            self.assertNotIn(EventType.TASK_FAILED, [event.event_type for event in result.events])

    async def test_reopens_sqlite_and_resumes_with_a_new_runner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "runtime.sqlite3"
            task = _task("restart-test")
            primary = ScriptedAgentAdapter(
                name="primary-agent",
                fail_on_steps=frozenset({1}),
            )

            with SQLiteRuntimeStore(database) as first_store:
                with self.assertRaises(ExecutionFailed) as failure:
                    await DurableRunner(first_store).run(task, (primary,))
                self.assertEqual(failure.exception.result.checkpoint.next_step, 1)
                self.assertEqual(failure.exception.result.status, TaskStatus.FAILED)

            fallback = ScriptedAgentAdapter(name="fallback-agent")
            with SQLiteRuntimeStore(database) as reopened_store:
                result = await DurableRunner(reopened_store).run(task, (fallback,))

            self.assertEqual(primary.calls, [0, 1])
            self.assertEqual(fallback.calls, [1, 2])
            self.assertEqual(result.status, TaskStatus.SUCCEEDED)
            self.assertEqual(len(result.artifacts), 3)
            self.assertIn(EventType.TASK_RESUMED, [event.event_type for event in result.events])

    async def test_completed_task_is_idempotent_on_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "runtime.sqlite3"
            task = _task("idempotent-test")
            first_agent = ScriptedAgentAdapter(name="first-agent")
            with SQLiteRuntimeStore(database) as first_store:
                first_result = await DurableRunner(first_store).run(task, (first_agent,))

            unused_agent = ScriptedAgentAdapter(name="unused-agent")
            with SQLiteRuntimeStore(database) as reopened_store:
                second_result = await DurableRunner(reopened_store).run(task, (unused_agent,))

            self.assertEqual(first_agent.calls, [0, 1, 2])
            self.assertEqual(unused_agent.calls, [])
            self.assertEqual(second_result.checkpoint, first_result.checkpoint)
            self.assertEqual(second_result.artifacts, first_result.artifacts)

    async def test_invalid_output_reroutes_to_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            invalid = InvalidOutputAdapter()
            fallback = ScriptedAgentAdapter(name="fallback-agent")
            with SQLiteRuntimeStore(Path(directory) / "runtime.sqlite3") as store:
                result = await DurableRunner(store).run(
                    _task("invalid-output-test"), (invalid, fallback)
                )

            self.assertEqual(invalid.calls, [0])
            self.assertEqual(fallback.calls, [0, 1, 2])
            self.assertTrue(result.recovered)

    async def test_nonrecoverable_error_does_not_try_fallback(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            SQLiteRuntimeStore(Path(directory) / "runtime.sqlite3") as store,
        ):
            fallback = ScriptedAgentAdapter(name="unused-agent")
            with self.assertRaises(ExecutionFailed) as failure:
                await DurableRunner(store).run(
                    _task("nonrecoverable-test"),
                    (BuggyAdapter(), fallback),
                )

            self.assertEqual(fallback.calls, [])
            self.assertEqual(failure.exception.result.status, TaskStatus.FAILED)
            self.assertFalse(failure.exception.result.recovered)
            self.assertFalse(failure.exception.result.recovery_attempted)

    async def test_all_fallbacks_exhausted_is_not_recovered(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            SQLiteRuntimeStore(Path(directory) / "runtime.sqlite3") as store,
        ):
            first = ScriptedAgentAdapter(name="first-agent", fail_on_steps=frozenset({0}))
            second = ScriptedAgentAdapter(name="second-agent", fail_on_steps=frozenset({0}))
            with self.assertRaises(ExecutionFailed) as failure:
                await DurableRunner(store).run(
                    _task("exhausted-test"),
                    (first, second),
                )

            self.assertEqual(first.calls, [0])
            self.assertEqual(second.calls, [0])
            self.assertEqual(failure.exception.result.failure_count, 2)
            self.assertFalse(failure.exception.result.recovered)

    async def test_three_adapter_chain_can_fail_over_twice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = ScriptedAgentAdapter(name="first-agent", fail_on_steps=frozenset({1}))
            second = ScriptedAgentAdapter(name="second-agent", fail_on_steps=frozenset({1}))
            third = ScriptedAgentAdapter(name="third-agent")
            with SQLiteRuntimeStore(Path(directory) / "runtime.sqlite3") as store:
                result = await DurableRunner(store).run(
                    _task("three-agent-test"),
                    (first, second, third),
                )

            self.assertEqual(first.calls, [0, 1])
            self.assertEqual(second.calls, [1])
            self.assertEqual(third.calls, [1, 2])
            self.assertEqual(result.failure_count, 2)
            self.assertTrue(result.recovered)

    async def test_user_facing_demo_records_one_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace = await run_checkpoint_failover_demo_async(Path(directory) / "runtime.sqlite3")

        self.assertEqual(trace["status"], "succeeded")
        self.assertTrue(trace["recovered"])
        self.assertEqual(trace["failure_count"], 1)
        self.assertEqual(trace["primary_calls"], [0, 1])
        self.assertEqual(trace["fallback_calls"], [1, 2])


class RuntimeProcessRecoveryTests(unittest.TestCase):
    def test_os_process_exit_then_new_process_resumes_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "runtime.sqlite3"
            repository = Path(__file__).resolve().parents[1]
            helper = repository / "tests" / "helpers" / "runtime_process_worker.py"
            environment = os.environ.copy()
            source_root = repository / "src"
            existing_pythonpath = environment.get("PYTHONPATH")
            environment["PYTHONPATH"] = (
                str(source_root)
                if not existing_pythonpath
                else os.pathsep.join((str(source_root), existing_pythonpath))
            )

            crashed = subprocess.run(
                [sys.executable, str(helper), "crash", str(database)],
                cwd=repository,
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(
                crashed.returncode,
                17,
                msg=f"stdout:\n{crashed.stdout}\nstderr:\n{crashed.stderr}",
            )

            with SQLiteRuntimeStore(database) as interrupted_store:
                self.assertEqual(
                    interrupted_store.get_status("process-recovery"),
                    TaskStatus.RUNNING,
                )
                self.assertEqual(
                    interrupted_store.load_checkpoint("process-recovery").next_step,
                    1,
                )
                self.assertEqual(
                    [
                        artifact.step_index
                        for artifact in interrupted_store.list_artifacts("process-recovery")
                    ],
                    [0],
                )

            resumed = subprocess.run(
                [sys.executable, str(helper), "resume", str(database)],
                cwd=repository,
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(
                resumed.returncode,
                0,
                msg=f"stdout:\n{resumed.stdout}\nstderr:\n{resumed.stderr}",
            )

            with SQLiteRuntimeStore(database) as recovered_store:
                self.assertEqual(
                    recovered_store.get_status("process-recovery"),
                    TaskStatus.SUCCEEDED,
                )
                self.assertEqual(
                    recovered_store.load_checkpoint("process-recovery").next_step,
                    3,
                )
                artifacts = recovered_store.list_artifacts("process-recovery")
                self.assertEqual([artifact.step_index for artifact in artifacts], [0, 1, 2])
                self.assertEqual(
                    [artifact.producer for artifact in artifacts],
                    ["process-primary", "process-fallback", "process-fallback"],
                )
                events = recovered_store.list_events("process-recovery")
                self.assertIn(EventType.TASK_RESUMED, [event.event_type for event in events])
                self.assertEqual(
                    [
                        event.step_index
                        for event in events
                        if event.event_type is EventType.ATTEMPT_STARTED
                        and event.agent_name == "process-fallback"
                    ],
                    [1, 2],
                )


class RuntimeStoreIntegrityTests(unittest.TestCase):
    def test_checkpoint_commit_rejects_a_stale_revision(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            SQLiteRuntimeStore(Path(directory) / "runtime.sqlite3") as store,
        ):
            task = _task("conflict-test")
            original = store.ensure_task(task)
            store.transition_status(
                task.task_id,
                TaskStatus.RUNNING,
                event_type=EventType.TASK_STARTED,
                detail="start integrity test",
            )
            artifact = Artifact.create(
                task_id=task.task_id,
                step_index=0,
                producer="agent-a",
                content="completed:prepare data",
            )
            advanced = original.advance(artifact)
            store.commit_step(
                artifact=artifact,
                expected_checkpoint=original,
                new_checkpoint=advanced,
            )

            with self.assertRaises(CheckpointConflict):
                store.commit_step(
                    artifact=artifact,
                    expected_checkpoint=original,
                    new_checkpoint=advanced,
                )

    def test_task_id_boundary_can_create_a_canonical_artifact(self) -> None:
        task = _task("a" * 96)

        artifact = Artifact.create(
            task_id=task.task_id,
            step_index=0,
            producer="agent-a",
            content="valid boundary artifact",
        )

        self.assertLessEqual(len(artifact.artifact_id), 128)
        with self.assertRaises(ValueError):
            _task("a" * 97)

    def test_changed_task_definition_is_rejected(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            SQLiteRuntimeStore(Path(directory) / "runtime.sqlite3") as store,
        ):
            store.ensure_task(_task("definition-test"))
            changed = Task(
                task_id="definition-test",
                objective="A different objective.",
                steps=("prepare data",),
            )

            with self.assertRaises(TaskDefinitionMismatch):
                store.ensure_task(changed)

    def test_corrupted_artifact_is_detected_after_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "runtime.sqlite3"
            task = Task(
                task_id="corruption-test",
                objective="Commit one immutable artifact.",
                steps=("prepare data",),
            )
            with SQLiteRuntimeStore(database) as store:
                checkpoint = store.ensure_task(task)
                store.transition_status(
                    task.task_id,
                    TaskStatus.RUNNING,
                    event_type=EventType.TASK_STARTED,
                    detail="start corruption test",
                )
                artifact = Artifact.create(
                    task_id=task.task_id,
                    step_index=0,
                    producer="agent-a",
                    content="original content",
                )
                store.commit_step(
                    artifact=artifact,
                    expected_checkpoint=checkpoint,
                    new_checkpoint=checkpoint.advance(artifact),
                )

            with sqlite3.connect(database) as connection:
                connection.execute(
                    "UPDATE artifacts SET content = ? WHERE artifact_id = ?",
                    ("tampered content", artifact.artifact_id),
                )

            with (
                SQLiteRuntimeStore(database) as reopened_store,
                self.assertRaises(CorruptStoreError),
            ):
                reopened_store.load_checkpoint(task.task_id)

    def test_atomic_commit_rolls_back_artifact_when_checkpoint_update_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "runtime.sqlite3"
            task = _task("rollback-test")
            with SQLiteRuntimeStore(database) as store:
                checkpoint = store.ensure_task(task)
                store.transition_status(
                    task.task_id,
                    TaskStatus.RUNNING,
                    event_type=EventType.TASK_STARTED,
                    detail="start rollback test",
                )

            with sqlite3.connect(database) as connection:
                connection.execute(
                    """
                    CREATE TRIGGER fail_checkpoint_update
                    BEFORE UPDATE OF revision ON checkpoints
                    BEGIN
                        SELECT RAISE(ABORT, 'injected checkpoint failure');
                    END
                    """
                )

            artifact = Artifact.create(
                task_id=task.task_id,
                step_index=0,
                producer="agent-a",
                content="must roll back",
            )
            with SQLiteRuntimeStore(database) as store:
                with self.assertRaises(RuntimeStoreError):
                    store.commit_step(
                        artifact=artifact,
                        expected_checkpoint=checkpoint,
                        new_checkpoint=checkpoint.advance(artifact),
                    )
                self.assertEqual(store.list_artifacts(task.task_id), ())
                self.assertEqual(store.load_checkpoint(task.task_id), checkpoint)

    def test_store_rejects_commit_while_task_is_pending(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            SQLiteRuntimeStore(Path(directory) / "runtime.sqlite3") as store,
        ):
            task = _task("pending-commit-test")
            checkpoint = store.ensure_task(task)
            artifact = Artifact.create(
                task_id=task.task_id,
                step_index=0,
                producer="agent-a",
                content="not allowed yet",
            )

            with self.assertRaises(RuntimeStoreError):
                store.commit_step(
                    artifact=artifact,
                    expected_checkpoint=checkpoint,
                    new_checkpoint=checkpoint.advance(artifact),
                )

    def test_store_rejects_commit_past_final_step(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            SQLiteRuntimeStore(Path(directory) / "runtime.sqlite3") as store,
        ):
            task = Task(
                task_id="past-final-test",
                objective="Complete one step only.",
                steps=("only step",),
            )
            checkpoint = store.ensure_task(task)
            store.transition_status(
                task.task_id,
                TaskStatus.RUNNING,
                event_type=EventType.TASK_STARTED,
                detail="start final-boundary test",
            )
            first = Artifact.create(
                task_id=task.task_id,
                step_index=0,
                producer="agent-a",
                content="only valid artifact",
            )
            final_checkpoint = checkpoint.advance(first)
            store.commit_step(
                artifact=first,
                expected_checkpoint=checkpoint,
                new_checkpoint=final_checkpoint,
            )
            extra = Artifact.create(
                task_id=task.task_id,
                step_index=1,
                producer="agent-a",
                content="must be rejected",
            )

            with self.assertRaises(RuntimeStoreError):
                store.commit_step(
                    artifact=extra,
                    expected_checkpoint=final_checkpoint,
                    new_checkpoint=final_checkpoint.advance(extra),
                )

    def test_stale_status_transition_cannot_regress_completed_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "runtime.sqlite3"
            task = Task(
                task_id="status-cas-test",
                objective="Complete before a stale status write.",
                steps=("only step",),
            )
            with SQLiteRuntimeStore(database) as current_store:
                checkpoint = current_store.ensure_task(task)
                current_store.transition_status(
                    task.task_id,
                    TaskStatus.RUNNING,
                    event_type=EventType.TASK_STARTED,
                    detail="start status race test",
                )
                artifact = Artifact.create(
                    task_id=task.task_id,
                    step_index=0,
                    producer="agent-a",
                    content="complete before stale write",
                )
                current_store.commit_step(
                    artifact=artifact,
                    expected_checkpoint=checkpoint,
                    new_checkpoint=checkpoint.advance(artifact),
                )
                with StaleReadSQLiteStore(database) as stale_store:
                    current_store.transition_status(
                        task.task_id,
                        TaskStatus.SUCCEEDED,
                        event_type=EventType.TASK_COMPLETED,
                        detail="completed before stale writer",
                    )

                    with self.assertRaises(RuntimeStoreError):
                        stale_store.transition_status(
                            task.task_id,
                            TaskStatus.RECOVERING,
                            event_type=EventType.STEP_REROUTED,
                            detail="stale transition must fail",
                        )

                self.assertEqual(current_store.get_status(task.task_id), TaskStatus.SUCCEEDED)


if __name__ == "__main__":
    unittest.main()
