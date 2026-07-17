"""Deterministic tests for bounded concurrency across durable Tasks."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from mechanistgym.runtime import (
    Artifact,
    Checkpoint,
    DurableRunner,
    ExecutionSpec,
    RecoverableAgentError,
    RuntimeStoreError,
    SQLiteRuntimeStore,
    Task,
    TaskStatus,
)
from mechanistgym.runtime.async_demo import run_bounded_async_demo_async
from mechanistgym.runtime.testing import ScriptedAgentAdapter


def _task(task_id: str, *, steps: tuple[str, ...] = ("work",)) -> Task:
    return Task(task_id=task_id, objective=f"complete {task_id}", steps=steps)


class ConcurrencyProbe:
    """Observe active adapters and release each Task deterministically."""

    def __init__(self, task_ids: tuple[str, ...]) -> None:
        self.entered: asyncio.Queue[str] = asyncio.Queue()
        self.release = {task_id: asyncio.Event() for task_id in task_ids}
        self.active = 0
        self.max_active = 0


class GateAdapter:
    """Block one-step Tasks until their test-owned Event is released."""

    name = "gate-agent"

    def __init__(self, probe: ConcurrencyProbe) -> None:
        self.probe = probe
        self.calls: list[str] = []

    async def execute_step(
        self,
        task: Task,
        *,
        step_index: int,
        artifacts: tuple[Artifact, ...],
    ) -> Artifact:
        if step_index != 0 or artifacts:
            raise AssertionError("GateAdapter accepts only fresh one-step Tasks")
        self.calls.append(task.task_id)
        self.probe.active += 1
        self.probe.max_active = max(self.probe.max_active, self.probe.active)
        await self.probe.entered.put(task.task_id)
        try:
            await self.probe.release[task.task_id].wait()
        finally:
            self.probe.active -= 1
        return Artifact.create(
            task_id=task.task_id,
            step_index=step_index,
            producer=self.name,
            content=f"completed:{task.task_id}",
        )


class BlockingStepAdapter:
    """Commit earlier steps, then expose cancellation at one selected step."""

    def __init__(self, name: str, *, block_step: int, started: asyncio.Event) -> None:
        self.name = name
        self.block_step = block_step
        self.started = started
        self.release = asyncio.Event()
        self.cancelled = False
        self.calls: list[int] = []

    async def execute_step(
        self,
        task: Task,
        *,
        step_index: int,
        artifacts: tuple[Artifact, ...],
    ) -> Artifact:
        if len(artifacts) != step_index:
            raise AssertionError("adapter received a non-contiguous Artifact prefix")
        self.calls.append(step_index)
        if step_index == self.block_step:
            self.started.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return Artifact.create(
            task_id=task.task_id,
            step_index=step_index,
            producer=self.name,
            content=f"completed:{task.steps[step_index]}",
        )


class SignaledFailureAdapter:
    """Raise a recoverable failure after signaling deterministic test progress."""

    name = "terminal-agent"

    def __init__(self, failed: asyncio.Event) -> None:
        self.failed = failed
        self.calls: list[int] = []

    async def execute_step(
        self,
        task: Task,
        *,
        step_index: int,
        artifacts: tuple[Artifact, ...],
    ) -> Artifact:
        del task, artifacts
        self.calls.append(step_index)
        self.failed.set()
        raise RecoverableAgentError("injected terminal failure")


class SelectiveFailureStore(SQLiteRuntimeStore):
    """Inject one infrastructure failure without affecting a sibling Task."""

    def __init__(self, path: Path, *, failing_task_id: str, failure_seen: asyncio.Event) -> None:
        super().__init__(path)
        self.failing_task_id = failing_task_id
        self.failure_seen = failure_seen

    def ensure_task(self, task: Task) -> Checkpoint:
        if task.task_id == self.failing_task_id:
            self.failure_seen.set()
            raise RuntimeStoreError("injected infrastructure failure")
        return super().ensure_task(task)


class FailingCommitStore(SQLiteRuntimeStore):
    """Raise an infrastructure error when selected Tasks try to commit."""

    def __init__(self, path: Path, *, failing_task_ids: frozenset[str]) -> None:
        super().__init__(path)
        self.failing_task_ids = failing_task_ids

    def commit_step(
        self,
        *,
        artifact: Artifact,
        expected_checkpoint: Checkpoint,
        new_checkpoint: Checkpoint,
    ) -> None:
        if artifact.task_id in self.failing_task_ids:
            raise RuntimeStoreError(f"injected commit failure for {artifact.task_id}")
        super().commit_step(
            artifact=artifact,
            expected_checkpoint=expected_checkpoint,
            new_checkpoint=new_checkpoint,
        )


class BarrierOutcomeAdapter:
    """Release several active Tasks together, optionally self-cancelling one."""

    name = "barrier-outcome-agent"

    def __init__(self, *, expected_entries: int, cancel_task_id: str | None = None) -> None:
        self.expected_entries = expected_entries
        self.cancel_task_id = cancel_task_id
        self.entries = 0
        self.ready = asyncio.Event()

    async def execute_step(
        self,
        task: Task,
        *,
        step_index: int,
        artifacts: tuple[Artifact, ...],
    ) -> Artifact:
        if step_index != 0 or artifacts:
            raise AssertionError("BarrierOutcomeAdapter accepts fresh one-step Tasks")
        self.entries += 1
        if self.entries == self.expected_entries:
            self.ready.set()
        await self.ready.wait()
        if task.task_id == self.cancel_task_id:
            raise asyncio.CancelledError
        return Artifact.create(
            task_id=task.task_id,
            step_index=step_index,
            producer=self.name,
            content=f"completed:{task.task_id}",
        )


class NamedOnlyAdapter:
    """Malformed adapter fixture without the required execution method."""

    name = "named-only"


class RuntimeConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_demo_shows_bounded_overlap_and_isolated_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace = await asyncio.wait_for(
                run_bounded_async_demo_async(Path(directory) / "runtime.sqlite3"),
                timeout=5.0,
            )

        self.assertEqual(trace["max_concurrency"], 2)
        self.assertEqual(trace["observed_max_active"], 2)
        self.assertEqual(trace["result_order"], ["batch-a", "batch-b", "batch-c"])
        self.assertEqual(
            trace["statuses"],
            {"batch-a": "succeeded", "batch-b": "succeeded", "batch-c": "succeeded"},
        )
        self.assertEqual(
            trace["recovered"],
            {"batch-a": False, "batch-b": True, "batch-c": False},
        )
        self.assertEqual(trace["fallback_calls"], [("batch-b", 1)])

    async def test_public_demo_rejects_a_reused_database_instead_of_hanging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.sqlite3"
            with SQLiteRuntimeStore(path):
                pass
            with self.assertRaisesRegex(ValueError, "new or empty database"):
                await asyncio.wait_for(
                    run_bounded_async_demo_async(path),
                    timeout=5.0,
                )

    async def test_distinct_tasks_overlap_never_exceed_bound_and_keep_input_order(self) -> None:
        task_ids = ("async-a", "async-b", "async-c")
        tasks = tuple(_task(task_id) for task_id in task_ids)
        probe = ConcurrencyProbe(task_ids)
        adapter = GateAdapter(probe)

        with (
            tempfile.TemporaryDirectory() as directory,
            SQLiteRuntimeStore(Path(directory) / "runtime.sqlite3") as store,
        ):
            execution = asyncio.create_task(
                DurableRunner(store).run_many(
                    tuple(ExecutionSpec(task, (adapter,)) for task in tasks),
                    max_concurrency=2,
                )
            )
            first = await asyncio.wait_for(probe.entered.get(), timeout=5.0)
            second = await asyncio.wait_for(probe.entered.get(), timeout=5.0)
            self.assertEqual(len({first, second}), 2)
            self.assertEqual(probe.active, 2)
            self.assertEqual(probe.max_active, 2)
            await asyncio.sleep(0)
            self.assertTrue(probe.entered.empty())

            probe.release[second].set()
            third = await asyncio.wait_for(probe.entered.get(), timeout=5.0)
            self.assertNotIn(third, {first, second})
            for release in probe.release.values():
                release.set()

            results = await asyncio.wait_for(execution, timeout=5.0)

        self.assertEqual([result.task.task_id for result in results], list(task_ids))
        self.assertTrue(all(result.status is TaskStatus.SUCCEEDED for result in results))
        self.assertEqual(probe.max_active, 2)

    async def test_terminal_agent_failure_does_not_cancel_active_sibling(self) -> None:
        success_started = asyncio.Event()
        failure_seen = asyncio.Event()
        success = BlockingStepAdapter("success-agent", block_step=0, started=success_started)
        failure = SignaledFailureAdapter(failure_seen)
        success_task = _task("isolated-success")
        failed_task = _task("isolated-failure")

        with (
            tempfile.TemporaryDirectory() as directory,
            SQLiteRuntimeStore(Path(directory) / "runtime.sqlite3") as store,
        ):
            batch = asyncio.create_task(
                DurableRunner(store).run_many(
                    (
                        ExecutionSpec(success_task, (success,)),
                        ExecutionSpec(failed_task, (failure,)),
                    ),
                    max_concurrency=2,
                )
            )
            await asyncio.wait_for(success_started.wait(), timeout=5.0)
            await asyncio.wait_for(failure_seen.wait(), timeout=5.0)
            await asyncio.sleep(0)
            self.assertFalse(success.cancelled)
            self.assertFalse(batch.done())
            success.release.set()
            results = await asyncio.wait_for(batch, timeout=5.0)

        self.assertEqual(
            [result.status for result in results],
            [TaskStatus.SUCCEEDED, TaskStatus.FAILED],
        )
        self.assertFalse(success.cancelled)

    async def test_terminal_failure_releases_slot_for_queued_task(self) -> None:
        failed_task = _task("slot-failure")
        success_task = _task("slot-success")
        failure = ScriptedAgentAdapter(
            name="failing-agent",
            fail_on_steps=frozenset({0}),
        )
        success = ScriptedAgentAdapter(name="queued-success-agent")

        with (
            tempfile.TemporaryDirectory() as directory,
            SQLiteRuntimeStore(Path(directory) / "runtime.sqlite3") as store,
        ):
            results = await DurableRunner(store).run_many(
                (
                    ExecutionSpec(failed_task, (failure,)),
                    ExecutionSpec(success_task, (success,)),
                ),
                max_concurrency=1,
            )

        self.assertEqual(
            [result.status for result in results],
            [TaskStatus.FAILED, TaskStatus.SUCCEEDED],
        )
        self.assertEqual(success.calls, [0])

    async def test_concurrent_checkpointed_failover_is_task_isolated(self) -> None:
        steps = ("prepare", "analyze", "report")
        recovering_task = _task("concurrent-recovery", steps=steps)
        normal_task = _task("concurrent-normal", steps=steps)
        primary = ScriptedAgentAdapter(
            name="recovering-primary",
            fail_on_steps=frozenset({1}),
        )
        fallback = ScriptedAgentAdapter(name="recovering-fallback")
        normal = ScriptedAgentAdapter(name="normal-agent")

        with (
            tempfile.TemporaryDirectory() as directory,
            SQLiteRuntimeStore(Path(directory) / "runtime.sqlite3") as store,
        ):
            results = await DurableRunner(store).run_many(
                (
                    ExecutionSpec(recovering_task, (primary, fallback)),
                    ExecutionSpec(normal_task, (normal,)),
                ),
                max_concurrency=2,
            )

        recovering_result, normal_result = results
        self.assertEqual(primary.calls, [0, 1])
        self.assertEqual(fallback.calls, [1, 2])
        self.assertEqual(normal.calls, [0, 1, 2])
        self.assertTrue(recovering_result.recovered)
        self.assertEqual(recovering_result.failure_count, 1)
        self.assertFalse(normal_result.recovered)
        self.assertEqual(normal_result.failure_count, 0)
        for result in results:
            self.assertTrue(all(a.task_id == result.task.task_id for a in result.artifacts))
            self.assertTrue(all(e.task_id == result.task.task_id for e in result.events))

    async def test_batch_cancellation_preserves_active_work_and_never_starts_queued_task(
        self,
    ) -> None:
        active_task = _task("cancel-active", steps=("prepare", "finish"))
        queued_task = _task("cancel-queued")
        started = asyncio.Event()
        active = BlockingStepAdapter("active-agent", block_step=1, started=started)
        queued = ScriptedAgentAdapter(name="queued-agent")

        with (
            tempfile.TemporaryDirectory() as directory,
            SQLiteRuntimeStore(Path(directory) / "runtime.sqlite3") as store,
        ):
            runner = DurableRunner(store)
            batch = asyncio.create_task(
                runner.run_many(
                    (
                        ExecutionSpec(active_task, (active,)),
                        ExecutionSpec(queued_task, (queued,)),
                    ),
                    max_concurrency=1,
                )
            )
            await asyncio.wait_for(started.wait(), timeout=5.0)
            batch.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await batch

            self.assertTrue(active.cancelled)
            self.assertEqual(active.calls, [0, 1])
            self.assertEqual(queued.calls, [])
            self.assertEqual(store.get_status(active_task.task_id), TaskStatus.RUNNING)
            self.assertEqual(store.load_checkpoint(active_task.task_id).next_step, 1)
            with self.assertRaises(RuntimeStoreError):
                store.get_status(queued_task.task_id)

            fresh = ScriptedAgentAdapter(name="fresh-agent")
            fresh_result = await runner.run_many(
                (ExecutionSpec(_task("after-cancellation"), (fresh,)),),
                max_concurrency=1,
            )
            self.assertEqual(fresh_result[0].status, TaskStatus.SUCCEEDED)

            fallback = ScriptedAgentAdapter(name="cancel-fallback")
            recovered = await runner.run(active_task, (fallback,))
            self.assertEqual(fallback.calls, [1])
            self.assertTrue(recovered.recovered)

    async def test_preflight_validation_happens_before_store_mutation(self) -> None:
        task = _task("preflight-task")
        adapter = ScriptedAgentAdapter(name="preflight-agent")
        spec = ExecutionSpec(task, (adapter,))

        with (
            tempfile.TemporaryDirectory() as directory,
            SQLiteRuntimeStore(Path(directory) / "runtime.sqlite3") as store,
        ):
            runner = DurableRunner(store)
            with self.assertRaises(TypeError):
                await runner.run_many((spec,), max_concurrency=True)
            with self.assertRaises(TypeError):
                await runner.run_many((spec,), max_concurrency=1.5)  # type: ignore[arg-type]
            with self.assertRaises(ValueError):
                await runner.run_many((spec,), max_concurrency=0)
            with self.assertRaises(ValueError):
                await runner.run_many((spec, spec), max_concurrency=1)
            with self.assertRaises(ValueError):
                await runner.run_many((ExecutionSpec(task, ()),), max_concurrency=1)
            with self.assertRaises(TypeError):
                await runner.run_many((object(),), max_concurrency=1)  # type: ignore[arg-type]
            with self.assertRaises(TypeError):
                ExecutionSpec(object(), (adapter,))  # type: ignore[arg-type]
            with self.assertRaises(TypeError):
                ExecutionSpec(
                    _task("malformed-adapter"),
                    (NamedOnlyAdapter(),),  # type: ignore[arg-type]
                )

            self.assertEqual(await runner.run_many((), max_concurrency=1), ())
            self.assertEqual(adapter.calls, [])
            with self.assertRaises(RuntimeStoreError):
                store.get_status(task.task_id)
            with self.assertRaises(RuntimeStoreError):
                store.get_status("malformed-adapter")

    async def test_execution_uses_an_immutable_snapshot_of_mutable_adapter_chain(self) -> None:
        task = _task("mutable-direct-chain", steps=("prepare", "finish"))
        started = asyncio.Event()
        adapter = BlockingStepAdapter("snapshotted-agent", block_step=0, started=started)
        chain = [adapter]

        with (
            tempfile.TemporaryDirectory() as directory,
            SQLiteRuntimeStore(Path(directory) / "runtime.sqlite3") as store,
        ):
            execution = asyncio.create_task(DurableRunner(store).run(task, chain))
            await asyncio.wait_for(started.wait(), timeout=5.0)
            chain.clear()
            adapter.release.set()
            result = await asyncio.wait_for(execution, timeout=5.0)

        self.assertEqual(result.status, TaskStatus.SUCCEEDED)
        self.assertEqual(adapter.calls, [0, 1])

    async def test_execution_spec_canonicalizes_list_and_generator_chains(self) -> None:
        list_adapter = ScriptedAgentAdapter(name="list-snapshot-agent")
        original = [list_adapter]
        list_spec = ExecutionSpec(
            _task("mutable-spec-chain"),
            original,  # type: ignore[arg-type]
        )
        original.clear()

        generator_adapter = ScriptedAgentAdapter(name="generator-snapshot-agent")
        generator_spec = ExecutionSpec(
            _task("generator-spec-chain"),
            iter((generator_adapter,)),  # type: ignore[arg-type]
        )

        self.assertEqual(list_spec.failover_chain, (list_adapter,))
        self.assertEqual(generator_spec.failover_chain, (generator_adapter,))
        with (
            tempfile.TemporaryDirectory() as directory,
            SQLiteRuntimeStore(Path(directory) / "runtime.sqlite3") as store,
        ):
            results = await DurableRunner(store).run_many(
                (list_spec, generator_spec),
                max_concurrency=2,
            )

        self.assertTrue(all(result.status is TaskStatus.SUCCEEDED for result in results))
        self.assertEqual(list_adapter.calls, [0])
        self.assertEqual(generator_adapter.calls, [0])

    async def test_infrastructure_error_settles_active_sibling_and_stops_queued_task(self) -> None:
        success_task = _task("infra-sibling")
        failing_task = _task("infra-failure")
        queued_task = _task("infra-queued")
        success_started = asyncio.Event()
        failure_seen = asyncio.Event()
        success = BlockingStepAdapter("infra-success", block_step=0, started=success_started)
        unused = ScriptedAgentAdapter(name="infra-unused")
        queued = ScriptedAgentAdapter(name="infra-queued-agent")

        with (
            tempfile.TemporaryDirectory() as directory,
            SelectiveFailureStore(
                Path(directory) / "runtime.sqlite3",
                failing_task_id=failing_task.task_id,
                failure_seen=failure_seen,
            ) as store,
        ):
            batch = asyncio.create_task(
                DurableRunner(store).run_many(
                    (
                        ExecutionSpec(success_task, (success,)),
                        ExecutionSpec(failing_task, (unused,)),
                        ExecutionSpec(queued_task, (queued,)),
                    ),
                    max_concurrency=2,
                )
            )
            await asyncio.wait_for(success_started.wait(), timeout=5.0)
            await asyncio.wait_for(failure_seen.wait(), timeout=5.0)
            await asyncio.sleep(0)
            self.assertFalse(batch.done())
            self.assertEqual(queued.calls, [])
            with self.assertRaises(RuntimeStoreError):
                store.get_status(queued_task.task_id)
            success.release.set()
            with self.assertRaisesRegex(
                RuntimeStoreError,
                "injected infrastructure failure",
            ):
                await asyncio.wait_for(batch, timeout=5.0)

            self.assertEqual(store.get_status(success_task.task_id), TaskStatus.SUCCEEDED)
            self.assertEqual(unused.calls, [])
            self.assertEqual(queued.calls, [])

    async def test_multiple_infrastructure_errors_are_grouped_without_loss(self) -> None:
        task_ids = ("multi-infra-a", "multi-infra-b")
        adapter = BarrierOutcomeAdapter(expected_entries=2)

        with (
            tempfile.TemporaryDirectory() as directory,
            FailingCommitStore(
                Path(directory) / "runtime.sqlite3",
                failing_task_ids=frozenset(task_ids),
            ) as store,
            self.assertRaises(BaseExceptionGroup) as captured,
        ):
            await asyncio.wait_for(
                DurableRunner(store).run_many(
                    tuple(ExecutionSpec(_task(task_id), (adapter,)) for task_id in task_ids),
                    max_concurrency=2,
                ),
                timeout=5.0,
            )

        errors = captured.exception.exceptions
        self.assertEqual(len(errors), 2)
        self.assertTrue(all(isinstance(error, RuntimeStoreError) for error in errors))
        self.assertEqual(
            {str(error) for error in errors},
            {f"injected commit failure for {task_id}" for task_id in task_ids},
        )

    async def test_child_cancellation_does_not_hide_infrastructure_error(self) -> None:
        cancelled_task = _task("mixed-cancel")
        infrastructure_task = _task("mixed-infra")
        adapter = BarrierOutcomeAdapter(
            expected_entries=2,
            cancel_task_id=cancelled_task.task_id,
        )

        with (
            tempfile.TemporaryDirectory() as directory,
            FailingCommitStore(
                Path(directory) / "runtime.sqlite3",
                failing_task_ids=frozenset({infrastructure_task.task_id}),
            ) as store,
            self.assertRaises(BaseExceptionGroup) as captured,
        ):
            await asyncio.wait_for(
                DurableRunner(store).run_many(
                    (
                        ExecutionSpec(cancelled_task, (adapter,)),
                        ExecutionSpec(infrastructure_task, (adapter,)),
                    ),
                    max_concurrency=2,
                ),
                timeout=5.0,
            )

        errors = captured.exception.exceptions
        self.assertEqual(len(errors), 2)
        self.assertTrue(any(isinstance(error, asyncio.CancelledError) for error in errors))
        self.assertTrue(any(isinstance(error, RuntimeStoreError) for error in errors))
