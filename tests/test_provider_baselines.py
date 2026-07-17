"""Acceptance tests for the R2 matched provider baseline protocol."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from mechanistgym.evaluation import (
    BaselineCondition,
    EndpointRegion,
    PricingSnapshot,
    ProviderBenchmarkManifest,
    run_matched_provider_baselines,
)
from mechanistgym.providers import (
    InMemoryProviderTelemetry,
    OpenAICompatibleAdapter,
    OpenAICompatibleConfig,
)
from mechanistgym.runtime import AgentAdapter, Task
from mechanistgym.runtime.testing import ScriptedAgentAdapter


class CountingCompletions:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    async def create(self, **request: object) -> SimpleNamespace:
        self.requests.append(request)
        messages = request["messages"]
        payload = json.loads(messages[-1]["content"])
        content = f"completed step {payload['step_index']}: {payload['step']}"
        return SimpleNamespace(
            id=f"request-{len(self.requests)}",
            model="qwen-test-snapshot",
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content=content),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )


class CountingClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=CountingCompletions())


class ProviderBaselineTests(unittest.IsolatedAsyncioTestCase):
    async def test_matched_conditions_account_for_repeated_work(self) -> None:
        task = Task(
            task_id="matched-provider-test",
            objective="Complete a three-step provider benchmark.",
            steps=("prepare", "analyze", "report"),
        )
        config = OpenAICompatibleConfig(
            provider="test-provider",
            base_url="https://example.invalid/v1",
            model="qwen-test-snapshot",
            api_key_env=None,
        )
        telemetry = InMemoryProviderTelemetry()
        client = CountingClient()
        manifest = ProviderBenchmarkManifest.from_config(
            config,
            task,
            endpoint_region=EndpointRegion.LOCAL_TEST,
        )

        def factory(*, name: str, run_id: str) -> AgentAdapter:
            return OpenAICompatibleAdapter(
                name=name,
                config=config,
                run_id=run_id,
                telemetry=telemetry,
                client=client,
            )

        report = await run_matched_provider_baselines(
            task,
            adapter_factory=factory,
            telemetry=telemetry,
            manifest=manifest,
            failure_step=1,
            pricing=PricingSnapshot(
                snapshot_id="test-prices-2026-07-16",
                model="qwen-test-snapshot",
                endpoint_region=EndpointRegion.LOCAL_TEST,
                token_tier="all-token-tiers",
                input_usd_per_million=2,
                output_usd_per_million=4,
            ),
            experiment_id="matched-test",
        )

        self.assertEqual(
            report.failure_injection,
            "post_response_pre_commit_graceful_reopen",
        )
        self.assertEqual(report.pricing.snapshot_id, "test-prices-2026-07-16")
        by_condition = {metric.condition: metric for metric in report.conditions}
        clean = by_condition[BaselineCondition.SEQUENTIAL]
        checkpoint_clean = by_condition[BaselineCondition.CHECKPOINT_CLEAN]
        resume = by_condition[BaselineCondition.CHECKPOINT_RESUME]
        restart = by_condition[BaselineCondition.RESTART_FROM_SCRATCH]

        self.assertEqual(clean.provider_calls, 3)
        self.assertEqual(checkpoint_clean.provider_calls, 3)
        self.assertEqual(resume.provider_calls, 4)
        self.assertEqual(restart.provider_calls, 5)
        self.assertEqual(clean.duplicated_provider_calls, 0)
        self.assertEqual(checkpoint_clean.duplicated_provider_calls, 0)
        self.assertEqual(resume.duplicated_provider_calls, 1)
        self.assertEqual(restart.duplicated_provider_calls, 2)
        self.assertEqual(resume.pre_failure_committed_steps, 1)
        self.assertEqual(resume.recomputed_committed_steps, 0)
        self.assertEqual(resume.preserved_committed_steps, 1)
        self.assertTrue(resume.prefix_checksums_match)
        self.assertEqual(restart.pre_failure_committed_steps, 1)
        self.assertEqual(restart.recomputed_committed_steps, 1)
        self.assertEqual(restart.preserved_committed_steps, 0)
        self.assertTrue(restart.prefix_checksums_match)
        self.assertEqual(
            (
                clean.total_tokens,
                checkpoint_clean.total_tokens,
                resume.total_tokens,
                restart.total_tokens,
            ),
            (45, 45, 60, 75),
        )
        self.assertAlmostEqual(clean.estimated_cost_usd or 0, (30 * 2 + 15 * 4) / 1_000_000)
        self.assertTrue(all(metric.completed for metric in report.conditions))
        self.assertTrue(all(metric.verification_passed for metric in report.conditions))
        self.assertEqual(len(client.chat.completions.requests), 15)
        self.assertEqual(len(report.calls), 15)
        self.assertEqual(report.manifest.requested_model, "qwen-test-snapshot")
        self.assertEqual(report.pricing.token_tier, "all-token-tiers")
        self.assertEqual(
            report.manifest.request_config_sha256, report.calls[0].request_config_sha256
        )
        self.assertNotIn("messages", report.to_json())

    async def test_unknown_usage_produces_unknown_cost(self) -> None:
        class NoUsageCompletions:
            async def create(self, **request: object) -> SimpleNamespace:
                messages = request["messages"]
                payload = json.loads(messages[-1]["content"])
                return SimpleNamespace(
                    id="request",
                    model="model",
                    choices=[
                        SimpleNamespace(
                            finish_reason="stop",
                            message=SimpleNamespace(content=f"step {payload['step_index']}"),
                        )
                    ],
                    usage=None,
                )

        task = Task(task_id="unknown-usage", objective="test", steps=("one",))
        telemetry = InMemoryProviderTelemetry()
        client = SimpleNamespace(chat=SimpleNamespace(completions=NoUsageCompletions()))
        config = OpenAICompatibleConfig(
            provider="test",
            base_url="https://example.invalid/v1",
            model="model",
            api_key_env=None,
        )
        manifest = ProviderBenchmarkManifest.from_config(
            config,
            task,
            endpoint_region=EndpointRegion.LOCAL_TEST,
        )

        def factory(*, name: str, run_id: str) -> AgentAdapter:
            return OpenAICompatibleAdapter(
                name=name,
                config=config,
                run_id=run_id,
                telemetry=telemetry,
                client=client,
            )

        report = await run_matched_provider_baselines(
            task,
            adapter_factory=factory,
            telemetry=telemetry,
            manifest=manifest,
            failure_step=0,
            pricing=PricingSnapshot(
                "test",
                "model",
                EndpointRegion.LOCAL_TEST,
                "all",
                1,
                1,
            ),
            experiment_id="unknown-test",
        )

        for metric in report.conditions:
            self.assertIsNone(metric.total_tokens)
            self.assertIsNone(metric.estimated_cost_usd)

    async def test_reused_experiment_id_cannot_contaminate_metrics(self) -> None:
        task = Task(task_id="collision-test", objective="test", steps=("one",))
        telemetry = InMemoryProviderTelemetry()
        client = CountingClient()
        config = OpenAICompatibleConfig(
            provider="test",
            base_url="https://example.invalid/v1",
            model="model",
            api_key_env=None,
        )
        manifest = ProviderBenchmarkManifest.from_config(
            config,
            task,
            endpoint_region=EndpointRegion.LOCAL_TEST,
        )

        def factory(*, name: str, run_id: str) -> AgentAdapter:
            return OpenAICompatibleAdapter(
                name=name,
                config=config,
                run_id=run_id,
                telemetry=telemetry,
                client=client,
            )

        await run_matched_provider_baselines(
            task,
            adapter_factory=factory,
            telemetry=telemetry,
            manifest=manifest,
            failure_step=0,
            experiment_id="same-id",
        )
        with self.assertRaisesRegex(ValueError, "already contains"):
            await run_matched_provider_baselines(
                task,
                adapter_factory=factory,
                telemetry=telemetry,
                manifest=manifest,
                failure_step=0,
                experiment_id="same-id",
            )

    async def test_completed_adapter_without_provider_telemetry_is_rejected(self) -> None:
        task = Task(task_id="missing-telemetry", objective="test", steps=("one",))
        telemetry = InMemoryProviderTelemetry()
        config = OpenAICompatibleConfig(
            provider="test",
            base_url="https://example.invalid/v1",
            model="model",
            api_key_env=None,
        )
        manifest = ProviderBenchmarkManifest.from_config(
            config,
            task,
            endpoint_region=EndpointRegion.LOCAL_TEST,
        )

        def factory(*, name: str, run_id: str) -> AgentAdapter:
            return ScriptedAgentAdapter(name=name)

        with self.assertRaisesRegex(RuntimeError, "does not match the controlled call protocol"):
            await run_matched_provider_baselines(
                task,
                adapter_factory=factory,
                telemetry=telemetry,
                manifest=manifest,
                failure_step=0,
                experiment_id="missing-telemetry",
            )

    async def test_adapter_configuration_must_match_manifest(self) -> None:
        task = Task(task_id="config-mismatch", objective="test", steps=("one",))
        telemetry = InMemoryProviderTelemetry()
        manifest_config = OpenAICompatibleConfig(
            provider="test",
            base_url="https://example.invalid/v1",
            model="declared-model",
            api_key_env=None,
        )
        actual_config = OpenAICompatibleConfig(
            provider="test",
            base_url="https://example.invalid/v1",
            model="different-model",
            api_key_env=None,
        )
        manifest = ProviderBenchmarkManifest.from_config(
            manifest_config,
            task,
            endpoint_region=EndpointRegion.LOCAL_TEST,
        )
        client = CountingClient()

        def factory(*, name: str, run_id: str) -> AgentAdapter:
            return OpenAICompatibleAdapter(
                name=name,
                config=actual_config,
                run_id=run_id,
                telemetry=telemetry,
                client=client,
            )

        with self.assertRaisesRegex(RuntimeError, "does not match the benchmark manifest"):
            await run_matched_provider_baselines(
                task,
                adapter_factory=factory,
                telemetry=telemetry,
                manifest=manifest,
                failure_step=0,
                experiment_id="config-mismatch",
            )

    async def test_experiment_id_cannot_escape_database_directory(self) -> None:
        task = Task(task_id="safe-path", objective="test", steps=("one",))
        config = OpenAICompatibleConfig(
            provider="test",
            base_url="https://example.invalid/v1",
            model="model",
            api_key_env=None,
        )
        manifest = ProviderBenchmarkManifest.from_config(
            config,
            task,
            endpoint_region=EndpointRegion.LOCAL_TEST,
        )

        def factory(*, name: str, run_id: str) -> AgentAdapter:
            raise AssertionError("unsafe experiment ID should fail before adapter creation")

        with self.assertRaisesRegex(ValueError, "experiment_id"):
            await run_matched_provider_baselines(
                task,
                adapter_factory=factory,
                telemetry=InMemoryProviderTelemetry(),
                manifest=manifest,
                failure_step=0,
                experiment_id="../../escape",
            )

    def test_qwen_endpoint_host_must_match_public_region(self) -> None:
        task = Task(task_id="region-binding", objective="test", steps=("one",))
        config = OpenAICompatibleConfig(
            provider="alibaba-model-studio",
            base_url="https://dashscope-us.aliyuncs.com/compatible-mode/v1",
            model="qwen3.6-flash-2026-04-16",
            api_key_env="DASHSCOPE_API_KEY",
            enable_thinking=False,
        )

        with self.assertRaisesRegex(ValueError, "does not match endpoint_region"):
            ProviderBenchmarkManifest.from_config(
                config,
                task,
                endpoint_region=EndpointRegion.SINGAPORE,
            )

        manifest = ProviderBenchmarkManifest.from_config(
            config,
            task,
            endpoint_region=EndpointRegion.US_VIRGINIA,
        )
        self.assertEqual(manifest.endpoint_region, EndpointRegion.US_VIRGINIA)
        self.assertFalse(manifest.enable_thinking)

    def test_pricing_rejects_nonfinite_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite"):
            PricingSnapshot(
                "bad",
                "model",
                EndpointRegion.LOCAL_TEST,
                "all",
                float("nan"),
                1,
            )
