"""Contract tests for the optional OpenAI-compatible provider adapter."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from openai import AsyncOpenAI

from mechanistgym.providers import (
    InMemoryProviderTelemetry,
    OpenAICompatibleAdapter,
    OpenAICompatibleConfig,
    PermanentProviderError,
    ProviderCallOutcome,
    ProviderConfigurationError,
    ProviderProtocolError,
    TransientProviderError,
)
from mechanistgym.runtime import Task


def _task() -> Task:
    return Task(
        task_id="provider-test",
        objective="Produce a small provider Artifact.",
        steps=("write the first result", "use the committed result"),
    )


def _response(
    content: str = "provider result",
    *,
    finish_reason: str | None = "stop",
    usage: object | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="request-secretish-identifier",
        model="qwen-test-snapshot",
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(content=content),
            )
        ],
        usage=usage,
    )


class FakeCompletions:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.requests: list[dict[str, object]] = []

    async def create(self, **request: object) -> object:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            return await outcome()
        return outcome


class FakeClient:
    def __init__(self, outcomes: list[object]) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(outcomes))


class FakeStatusError(RuntimeError):
    def __init__(self, status_code: int, *, code: str | None = None) -> None:
        super().__init__("raw body must not appear")
        self.status_code = status_code
        self.request_id = "private-provider-request-id"
        self.body = {"error": {"code": code}} if code is not None else None


class OpenAICompatibleProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.config = OpenAICompatibleConfig(
            provider="test-provider",
            base_url="https://example.invalid/compatible-mode/v1",
            model="qwen-test-snapshot",
            api_key_env="TEST_PROVIDER_SECRET",
            timeout_seconds=5,
            max_output_tokens=64,
        )

    async def test_success_returns_artifact_and_sanitized_usage(self) -> None:
        usage = SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18)
        client = FakeClient([_response(usage=usage)])
        telemetry = InMemoryProviderTelemetry()
        adapter = OpenAICompatibleAdapter(
            name="qwen-worker",
            config=self.config,
            run_id="success-run",
            telemetry=telemetry,
            client=client,
        )

        artifact = await adapter.execute_step(_task(), step_index=0, artifacts=())

        self.assertEqual(artifact.content, "provider result")
        self.assertEqual(artifact.producer, "qwen-worker")
        request = client.chat.completions.requests[0]
        self.assertFalse(request["stream"])
        self.assertEqual(request["model"], "qwen-test-snapshot")
        self.assertEqual(request["temperature"], 0.1)
        self.assertEqual(request["seed"], 42)
        self.assertEqual(len(request["messages"]), 2)

        [record] = telemetry.records
        self.assertEqual(record.outcome, ProviderCallOutcome.SUCCEEDED)
        self.assertEqual(record.input_tokens, 11)
        self.assertEqual(record.output_tokens, 7)
        self.assertEqual(record.total_tokens, 18)
        self.assertEqual(len(record.prompt_sha256), 64)
        self.assertEqual(len(record.request_id_hash or ""), 16)
        serialized = repr(record) + repr(adapter)
        self.assertNotIn("request-secretish-identifier", serialized)
        self.assertNotIn("TEST_VALUE_DO_NOT_LEAK", serialized)

    async def test_missing_usage_remains_unknown_instead_of_zero(self) -> None:
        telemetry = InMemoryProviderTelemetry()
        adapter = OpenAICompatibleAdapter(
            name="qwen-worker",
            config=self.config,
            run_id="unknown-usage",
            telemetry=telemetry,
            client=FakeClient([_response()]),
        )

        await adapter.execute_step(_task(), step_index=0, artifacts=())

        [record] = telemetry.records
        self.assertIsNone(record.input_tokens)
        self.assertIsNone(record.output_tokens)
        self.assertIsNone(record.total_tokens)

    async def test_rate_limit_is_recoverable_and_error_body_is_sanitized(self) -> None:
        telemetry = InMemoryProviderTelemetry()
        adapter = OpenAICompatibleAdapter(
            name="qwen-worker",
            config=self.config,
            run_id="rate-limit",
            telemetry=telemetry,
            client=FakeClient([FakeStatusError(429)]),
        )

        with self.assertRaisesRegex(TransientProviderError, "HTTP status 429") as failure:
            await adapter.execute_step(_task(), step_index=0, artifacts=())

        self.assertNotIn("raw body", str(failure.exception))
        [record] = telemetry.records
        self.assertEqual(record.outcome, ProviderCallOutcome.RECOVERABLE_ERROR)
        self.assertEqual(record.status_code, 429)
        self.assertEqual(record.error_type, "TransientProviderError")

    async def test_authentication_error_is_permanent(self) -> None:
        telemetry = InMemoryProviderTelemetry()
        adapter = OpenAICompatibleAdapter(
            name="qwen-worker",
            config=self.config,
            run_id="auth-failure",
            telemetry=telemetry,
            client=FakeClient([FakeStatusError(401)]),
        )

        with self.assertRaisesRegex(PermanentProviderError, "HTTP status 401"):
            await adapter.execute_step(_task(), step_index=0, artifacts=())

        [record] = telemetry.records
        self.assertEqual(record.outcome, ProviderCallOutcome.PERMANENT_ERROR)

    async def test_qwen_billing_429_is_permanent_but_rate_limit_is_recoverable(self) -> None:
        qwen_config = OpenAICompatibleConfig(
            provider="alibaba-model-studio",
            base_url="https://dashscope-us.aliyuncs.com/compatible-mode/v1",
            model="qwen-test-snapshot",
            api_key_env="TEST_PROVIDER_SECRET",
            enable_thinking=False,
        )
        billing = OpenAICompatibleAdapter(
            name="qwen-billing",
            config=qwen_config,
            run_id="billing",
            client=FakeClient([FakeStatusError(429, code="PrepaidBillOverdue")]),
        )
        throttled = OpenAICompatibleAdapter(
            name="qwen-throttled",
            config=qwen_config,
            run_id="throttled",
            client=FakeClient([FakeStatusError(429, code="Throttling.RateQuota")]),
        )

        with self.assertRaisesRegex(PermanentProviderError, "PrepaidBillOverdue"):
            await billing.execute_step(_task(), step_index=0, artifacts=())
        with self.assertRaises(TransientProviderError):
            await throttled.execute_step(_task(), step_index=0, artifacts=())

    async def test_ambiguous_qwen_429_fails_closed(self) -> None:
        qwen_config = OpenAICompatibleConfig(
            provider="alibaba-model-studio",
            base_url="https://dashscope-us.aliyuncs.com/compatible-mode/v1",
            model="qwen-test-snapshot",
            api_key_env="TEST_PROVIDER_SECRET",
            enable_thinking=False,
        )
        adapter = OpenAICompatibleAdapter(
            name="qwen-ambiguous",
            config=qwen_config,
            run_id="ambiguous",
            client=FakeClient([FakeStatusError(429, code="UnknownFutureQuotaCode")]),
        )
        with self.assertRaisesRegex(PermanentProviderError, "ambiguous Qwen"):
            await adapter.execute_step(_task(), step_index=0, artifacts=())

    async def test_truncated_output_is_a_recoverable_protocol_error(self) -> None:
        telemetry = InMemoryProviderTelemetry()
        adapter = OpenAICompatibleAdapter(
            name="qwen-worker",
            config=self.config,
            run_id="truncated",
            telemetry=telemetry,
            client=FakeClient([_response(finish_reason="length")]),
        )

        with self.assertRaises(ProviderProtocolError):
            await adapter.execute_step(_task(), step_index=0, artifacts=())

        [record] = telemetry.records
        self.assertEqual(record.outcome, ProviderCallOutcome.PROTOCOL_ERROR)
        self.assertEqual(record.finish_reason, "length")
        self.assertEqual(record.status_code, 200)

    async def test_nonterminal_or_unknown_finish_reason_is_rejected(self) -> None:
        for finish_reason in (None, "tool_calls"):
            with self.subTest(finish_reason=finish_reason):
                telemetry = InMemoryProviderTelemetry()
                adapter = OpenAICompatibleAdapter(
                    name="qwen-worker",
                    config=self.config,
                    run_id=f"finish-{finish_reason}",
                    telemetry=telemetry,
                    client=FakeClient([_response(finish_reason=finish_reason)]),
                )
                with self.assertRaises(ProviderProtocolError):
                    await adapter.execute_step(_task(), step_index=0, artifacts=())
                self.assertEqual(telemetry.records[0].status_code, 200)

    async def test_cancellation_is_recorded_and_propagated(self) -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        async def block() -> object:
            entered.set()
            await release.wait()
            return _response()

        telemetry = InMemoryProviderTelemetry()
        adapter = OpenAICompatibleAdapter(
            name="qwen-worker",
            config=self.config,
            run_id="cancelled",
            telemetry=telemetry,
            client=FakeClient([block]),
        )
        execution = asyncio.create_task(adapter.execute_step(_task(), step_index=0, artifacts=()))
        await asyncio.wait_for(entered.wait(), timeout=2)
        execution.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await execution

        [record] = telemetry.records
        self.assertEqual(record.outcome, ProviderCallOutcome.CANCELLED)

    async def test_timeout_is_recoverable_and_usage_unknown(self) -> None:
        telemetry = InMemoryProviderTelemetry()
        adapter = OpenAICompatibleAdapter(
            name="qwen-worker",
            config=self.config,
            run_id="timeout",
            telemetry=telemetry,
            client=FakeClient([TimeoutError("private transport detail")]),
        )
        with self.assertRaises(TransientProviderError):
            await adapter.execute_step(_task(), step_index=0, artifacts=())
        [record] = telemetry.records
        self.assertEqual(record.outcome, ProviderCallOutcome.RECOVERABLE_ERROR)
        self.assertIsNone(record.total_tokens)

    async def test_missing_choice_is_a_protocol_error(self) -> None:
        response = SimpleNamespace(
            id="request",
            model="model",
            choices=[],
            usage=None,
        )
        adapter = OpenAICompatibleAdapter(
            name="qwen-worker",
            config=self.config,
            run_id="missing-choice",
            client=FakeClient([response]),
        )
        with self.assertRaises(ProviderProtocolError):
            await adapter.execute_step(_task(), step_index=0, artifacts=())

    async def test_unset_key_fails_without_leaking_or_sending(self) -> None:
        adapter = OpenAICompatibleAdapter(
            name="qwen-worker",
            config=self.config,
            run_id="missing-key",
        )
        with (
            patch.dict(os.environ, {}, clear=True),
            self.assertRaisesRegex(ProviderConfigurationError, "TEST_PROVIDER_SECRET"),
        ):
            await adapter.execute_step(_task(), step_index=0, artifacts=())

    async def test_owned_sdk_client_disables_hidden_retries(self) -> None:
        created: list[dict[str, object]] = []

        class FakeSDKClient:
            def __init__(self, **options: object) -> None:
                created.append(options)
                self.closed = False

            async def close(self) -> None:
                self.closed = True

        fake_module = SimpleNamespace(AsyncOpenAI=FakeSDKClient)
        adapter = OpenAICompatibleAdapter(
            name="qwen-worker",
            config=self.config,
            run_id="sdk-options",
        )
        with (
            patch.dict(os.environ, {"TEST_PROVIDER_SECRET": "TEST_VALUE_DO_NOT_LEAK"}),
            patch.dict(sys.modules, {"openai": fake_module}),
        ):
            client = adapter._get_client()
            self.assertEqual(created[0]["max_retries"], 0)
            self.assertEqual(created[0]["timeout"], 5)
            self.assertEqual(
                created[0]["base_url"],
                "https://example.invalid/compatible-mode/v1/",
            )
            self.assertNotIn("TEST_VALUE_DO_NOT_LEAK", repr(adapter))
            await adapter.aclose()
            self.assertTrue(client.closed)

    async def test_real_sdk_mock_transport_sends_one_https_request(self) -> None:
        captured: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(
                200,
                json={
                    "id": "wire-request-id",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "qwen-test-snapshot",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": "wire result"},
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 9,
                        "completion_tokens": 3,
                        "total_tokens": 12,
                    },
                },
            )

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        sdk_client = AsyncOpenAI(
            api_key="WIRE_TEST_SECRET",
            base_url="https://example.invalid/compatible-mode/v1",
            timeout=5,
            max_retries=0,
            http_client=http_client,
        )
        telemetry = InMemoryProviderTelemetry()
        adapter = OpenAICompatibleAdapter(
            name="wire-worker",
            config=self.config,
            run_id="wire-test",
            telemetry=telemetry,
            client=sdk_client,
        )
        try:
            artifact = await adapter.execute_step(_task(), step_index=0, artifacts=())
        finally:
            await sdk_client.close()

        self.assertEqual(artifact.content, "wire result")
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].url.path, "/compatible-mode/v1/chat/completions")
        self.assertEqual(captured[0].headers["authorization"], "Bearer WIRE_TEST_SECRET")
        self.assertNotIn("WIRE_TEST_SECRET", repr(telemetry.records))

    async def test_real_sdk_qwen_429_is_classified_without_hidden_retry(self) -> None:
        qwen_config = OpenAICompatibleConfig(
            provider="alibaba-model-studio",
            base_url="https://dashscope-us.aliyuncs.com/compatible-mode/v1",
            model="qwen-test-snapshot",
            api_key_env="TEST_PROVIDER_SECRET",
            enable_thinking=False,
        )
        cases = (
            ("PrepaidBillOverdue", PermanentProviderError, ProviderCallOutcome.PERMANENT_ERROR),
            (
                "Throttling.RateQuota",
                TransientProviderError,
                ProviderCallOutcome.RECOVERABLE_ERROR,
            ),
        )

        def make_handler(
            captured: list[httpx.Request],
            error_code: str,
        ) -> object:
            async def handler(request: httpx.Request) -> httpx.Response:
                captured.append(request)
                return httpx.Response(
                    429,
                    json={
                        "error": {
                            "message": "sanitized test provider failure",
                            "type": "rate_limit_error",
                            "param": None,
                            "code": error_code,
                        }
                    },
                )

            return handler

        for error_code, expected_error, expected_outcome in cases:
            with self.subTest(error_code=error_code):
                captured: list[httpx.Request] = []
                http_client = httpx.AsyncClient(
                    transport=httpx.MockTransport(make_handler(captured, error_code))
                )
                sdk_client = AsyncOpenAI(
                    api_key="WIRE_TEST_SECRET",
                    base_url=qwen_config.base_url,
                    timeout=5,
                    max_retries=0,
                    http_client=http_client,
                )
                telemetry = InMemoryProviderTelemetry()
                adapter = OpenAICompatibleAdapter(
                    name=f"qwen-wire-{error_code}",
                    config=qwen_config,
                    run_id=f"qwen-wire-{error_code}",
                    telemetry=telemetry,
                    client=sdk_client,
                )
                try:
                    with self.assertRaises(expected_error):
                        await adapter.execute_step(_task(), step_index=0, artifacts=())
                finally:
                    await sdk_client.close()

                self.assertEqual(len(captured), 1)
                self.assertEqual(captured[0].url.path, "/compatible-mode/v1/chat/completions")
                self.assertFalse(json.loads(captured[0].content)["enable_thinking"])
                [record] = telemetry.records
                self.assertEqual(record.status_code, 429)
                self.assertEqual(record.provider_error_code, error_code)
                self.assertEqual(record.outcome, expected_outcome)

    async def test_real_sdk_500_is_recoverable_without_hidden_retry(self) -> None:
        captured: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(
                500,
                json={
                    "error": {
                        "message": "sanitized test server failure",
                        "type": "server_error",
                        "param": None,
                        "code": "internal_error",
                    }
                },
            )

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        sdk_client = AsyncOpenAI(
            api_key="WIRE_TEST_SECRET",
            base_url=self.config.base_url,
            timeout=5,
            max_retries=0,
            http_client=http_client,
        )
        telemetry = InMemoryProviderTelemetry()
        adapter = OpenAICompatibleAdapter(
            name="wire-server-error",
            config=self.config,
            run_id="wire-server-error",
            telemetry=telemetry,
            client=sdk_client,
        )
        try:
            with self.assertRaises(TransientProviderError):
                await adapter.execute_step(_task(), step_index=0, artifacts=())
        finally:
            await sdk_client.close()

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].url.path, "/compatible-mode/v1/chat/completions")
        [record] = telemetry.records
        self.assertEqual(record.status_code, 500)
        self.assertEqual(record.outcome, ProviderCallOutcome.RECOVERABLE_ERROR)

    async def test_real_sdk_timeout_is_recoverable_without_hidden_retry(self) -> None:
        captured: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            raise httpx.ReadTimeout("controlled wire timeout", request=request)

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        sdk_client = AsyncOpenAI(
            api_key="WIRE_TEST_SECRET",
            base_url=self.config.base_url,
            timeout=5,
            max_retries=0,
            http_client=http_client,
        )
        telemetry = InMemoryProviderTelemetry()
        adapter = OpenAICompatibleAdapter(
            name="wire-timeout",
            config=self.config,
            run_id="wire-timeout",
            telemetry=telemetry,
            client=sdk_client,
        )
        try:
            with self.assertRaises(TransientProviderError):
                await adapter.execute_step(_task(), step_index=0, artifacts=())
        finally:
            await sdk_client.close()

        self.assertEqual(len(captured), 1)
        [record] = telemetry.records
        self.assertIsNone(record.status_code)
        self.assertEqual(record.outcome, ProviderCallOutcome.RECOVERABLE_ERROR)

    def test_config_rejects_credentials_embedded_in_base_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not contain credentials"):
            OpenAICompatibleConfig(
                provider="test",
                base_url="https://secret@example.invalid/v1",
                model="model",
                api_key_env=None,
            )

    def test_config_rejects_authenticated_plain_http(self) -> None:
        with self.assertRaisesRegex(ValueError, "must use HTTPS"):
            OpenAICompatibleConfig(
                provider="test",
                base_url="http://example.invalid/v1",
                model="model",
                api_key_env="SECRET",
            )

    def test_qwen_environment_requires_explicit_base_url_and_model(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            self.assertRaisesRegex(ProviderConfigurationError, "DASHSCOPE_BASE_URL"),
        ):
            OpenAICompatibleConfig.qwen_model_studio_from_env()

        with (
            patch.dict(
                os.environ,
                {"DASHSCOPE_BASE_URL": "https://dashscope-us.aliyuncs.com/compatible-mode/v1"},
                clear=True,
            ),
            self.assertRaisesRegex(ProviderConfigurationError, "DASHSCOPE_MODEL"),
        ):
            OpenAICompatibleConfig.qwen_model_studio_from_env()

    def test_qwen_environment_preserves_explicit_model_pin(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DASHSCOPE_BASE_URL": ("https://dashscope-us.aliyuncs.com/compatible-mode/v1"),
                "DASHSCOPE_MODEL": "qwen3.6-flash-2026-04-16",
            },
            clear=True,
        ):
            config = OpenAICompatibleConfig.qwen_model_studio_from_env()

        self.assertEqual(config.model, "qwen3.6-flash-2026-04-16")
        self.assertFalse(config.enable_thinking)
        self.assertEqual(config.api_key_env, "DASHSCOPE_API_KEY")

    def test_qwen_config_requires_explicit_thinking_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "enable_thinking"):
            OpenAICompatibleConfig(
                provider="alibaba-model-studio",
                base_url="https://dashscope-us.aliyuncs.com/compatible-mode/v1",
                model="qwen3.6-flash-2026-04-16",
                api_key_env="DASHSCOPE_API_KEY",
            )

    def test_config_rejects_boolean_numeric_values(self) -> None:
        with self.assertRaisesRegex(TypeError, "timeout_seconds"):
            OpenAICompatibleConfig(
                provider="test",
                base_url="https://example.invalid/v1",
                model="model",
                api_key_env=None,
                timeout_seconds=True,
            )
