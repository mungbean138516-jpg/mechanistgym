"""One-request-per-step adapter for OpenAI-compatible Chat Completions APIs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from mechanistgym.runtime import Artifact, InvalidAgentOutput, RecoverableAgentError, Task

from .telemetry import (
    InMemoryProviderTelemetry,
    ProviderCallOutcome,
    ProviderCallRecord,
    ProviderTelemetrySink,
)

_PROMPT_VERSION = "mechanistgym.step.v1"
PROMPT_VERSION = _PROMPT_VERSION
_QWEN_PROVIDER = "alibaba-model-studio"
_QWEN_PERMANENT_429_CODES = frozenset(
    {
        "Arrearage",
        "CommodityNotPurchased",
        "PostpaidBillOverdue",
        "PrepaidBillOverdue",
    }
)
_QWEN_TRANSIENT_429_CODES = frozenset(
    {
        "LimitRequests",
        "Throttling",
        "Throttling.AllocationQuota",
        "Throttling.BurstRate",
        "Throttling.RateQuota",
        "insufficient_quota",
        "limit_burst_rate",
        "limit_requests",
    }
)
_SAFE_PROVIDER_ERROR_CODE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SYSTEM_PROMPT = (
    "You are one worker in a resumable AI workflow. Complete only the requested step. "
    "Use the committed artifacts as durable context, return a concise work product, and do not "
    "claim that unprovided evidence exists. Do not reveal hidden chain-of-thought."
)


class ProviderAdapterError(RuntimeError):
    """Base class for sanitized provider-adapter failures."""


class ProviderConfigurationError(ProviderAdapterError):
    """A local dependency, credential, or request configuration is invalid."""


class PermanentProviderError(ProviderAdapterError):
    """A provider rejected a request that should not be silently rerouted."""


class TransientProviderError(RecoverableAgentError, ProviderAdapterError):
    """A visible transport or server failure that may be handed to a fallback."""


class ProviderProtocolError(InvalidAgentOutput, ProviderAdapterError):
    """A nominally successful response violated the Artifact output contract."""


class ProviderTelemetryError(ProviderAdapterError):
    """The configured fail-closed telemetry sink rejected a call record."""


@dataclass(frozen=True, slots=True)
class OpenAICompatibleConfig:
    """Non-secret configuration for one compatible Chat Completions endpoint."""

    provider: str
    base_url: str
    model: str
    api_key_env: str | None
    timeout_seconds: float = 60.0
    temperature: float = 0.1
    seed: int | None = 42
    max_output_tokens: int = 512
    enable_thinking: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str):
            raise TypeError("provider must be a string")
        if not isinstance(self.base_url, str):
            raise TypeError("base_url must be a string")
        if not isinstance(self.model, str):
            raise TypeError("model must be a string")
        if not self.provider.strip():
            raise ValueError("provider must not be empty")
        if not self.model.strip():
            raise ValueError("model must not be empty")
        if self.api_key_env is not None:
            if not isinstance(self.api_key_env, str):
                raise TypeError("api_key_env must be None or a string")
            if not self.api_key_env.strip():
                raise ValueError(
                    "api_key_env must be None or a non-empty environment-variable name"
                )
        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds, (int, float)
        ):
            raise TypeError("timeout_seconds must be a number")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not math.isfinite(self.timeout_seconds):
            raise ValueError("timeout_seconds must be finite")
        if isinstance(self.temperature, bool) or not isinstance(self.temperature, (int, float)):
            raise TypeError("temperature must be a number")
        if not 0 <= self.temperature < 2:
            raise ValueError("temperature must be in [0, 2)")
        if not math.isfinite(self.temperature):
            raise ValueError("temperature must be finite")
        if self.seed is not None:
            if isinstance(self.seed, bool) or not isinstance(self.seed, int):
                raise TypeError("seed must be None or an integer")
            if not 0 <= self.seed < 2**64:
                raise ValueError("seed must be an unsigned 64-bit integer")
        if isinstance(self.max_output_tokens, bool) or not isinstance(self.max_output_tokens, int):
            raise TypeError("max_output_tokens must be an integer")
        if self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        if self.enable_thinking is not None and not isinstance(self.enable_thinking, bool):
            raise TypeError("enable_thinking must be None or a boolean")

        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("base_url must not contain credentials, a query, or a fragment")
        if self.api_key_env is not None and parsed.scheme != "https":
            raise ValueError("credentialed provider endpoints must use HTTPS")
        if self.provider == _QWEN_PROVIDER:
            if parsed.path.rstrip("/") != "/compatible-mode/v1":
                raise ValueError("Qwen base_url must end with /compatible-mode/v1")
            if self.temperature == 0:
                raise ValueError("Qwen Model Studio requires temperature greater than zero")
            if self.enable_thinking is None:
                raise ValueError("Qwen Model Studio requires an explicit enable_thinking mode")
            if self.seed is not None and self.seed > 2**31 - 1:
                raise ValueError(
                    "Qwen OpenAI-compatible seed must not exceed the signed 32-bit maximum"
                )

    @classmethod
    def qwen_model_studio_from_env(cls) -> OpenAICompatibleConfig:
        """Build a pinned Qwen Model Studio configuration without reading the API key value."""

        base_url = os.getenv("DASHSCOPE_BASE_URL")
        if not base_url:
            raise ProviderConfigurationError(
                "DASHSCOPE_BASE_URL is required; copy the API host for the key's region"
            )
        model = os.getenv("DASHSCOPE_MODEL")
        if not model:
            raise ProviderConfigurationError(
                "DASHSCOPE_MODEL is required; pin the exact hosted model used by the experiment"
            )
        return cls(
            provider=_QWEN_PROVIDER,
            base_url=base_url,
            model=model,
            api_key_env="DASHSCOPE_API_KEY",
            enable_thinking=False,
        )


def request_config_sha256(config: OpenAICompatibleConfig) -> str:
    """Hash all non-secret request settings that can change benchmark behavior."""

    payload = {
        "provider": config.provider,
        "base_url": config.base_url.rstrip("/"),
        "model": config.model,
        "timeout_seconds": config.timeout_seconds,
        "temperature": config.temperature,
        "seed": config.seed,
        "max_output_tokens": config.max_output_tokens,
        "enable_thinking": config.enable_thinking,
        "prompt_version": _PROMPT_VERSION,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _request_id_hash(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def create_openai_compatible_client(config: OpenAICompatibleConfig) -> Any:
    """Create a caller-owned SDK client with visible retry and timeout behavior."""

    if config.api_key_env is None:
        api_key = "not-required"
    else:
        api_key = os.getenv(config.api_key_env)
        if not api_key:
            raise ProviderConfigurationError(
                f"required API key environment variable {config.api_key_env!r} is unset"
            )
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise ProviderConfigurationError(
            "install the optional provider dependency with "
            "`python -m pip install -e '.[provider-openai]'`"
        ) from exc

    return AsyncOpenAI(
        api_key=api_key,
        base_url=config.base_url.rstrip("/") + "/",
        timeout=config.timeout_seconds,
        max_retries=0,
    )


class OpenAICompatibleAdapter:
    """Execute one Task step with one non-streaming Chat Completions request.

    The official ``openai`` SDK is loaded only when a client is not injected. SDK retries are
    disabled so every provider attempt remains visible to runtime evaluation.
    """

    def __init__(
        self,
        *,
        name: str,
        config: OpenAICompatibleConfig,
        run_id: str,
        telemetry: ProviderTelemetrySink | None = None,
        client: Any | None = None,
    ) -> None:
        if not name.strip():
            raise ValueError("name must not be empty")
        if not run_id.strip():
            raise ValueError("run_id must not be empty")
        self.name = name
        self.config = config
        self.run_id = run_id
        self.telemetry = telemetry if telemetry is not None else InMemoryProviderTelemetry()
        self._client = client
        self._owns_client = False

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(name={self.name!r}, provider={self.config.provider!r}, "
            f"model={self.config.model!r}, run_id={self.run_id!r})"
        )

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        self._client = create_openai_compatible_client(self.config)
        self._owns_client = True
        return self._client

    async def aclose(self) -> None:
        """Close an internally created SDK client; injected clients remain caller-owned."""

        if self._owns_client and self._client is not None:
            await self._client.close()
            self._client = None
            self._owns_client = False

    @staticmethod
    def _prompt(
        task: Task,
        step_index: int,
        artifacts: tuple[Artifact, ...],
    ) -> list[dict[str, str]]:
        if len(artifacts) != step_index:
            raise ValueError("adapter received a non-contiguous committed Artifact prefix")
        for expected_step, artifact in enumerate(artifacts):
            if not isinstance(artifact, Artifact):
                raise TypeError("committed context must contain only Artifacts")
            if artifact.task_id != task.task_id or artifact.step_index != expected_step:
                raise ValueError("committed Artifacts must be an ordered prefix of this Task")
        payload = {
            "objective": task.objective,
            "step_index": step_index,
            "step": task.steps[step_index],
            "committed_artifacts": [
                {
                    "step_index": artifact.step_index,
                    "content": artifact.content,
                    "media_type": artifact.media_type,
                }
                for artifact in artifacts
            ],
        }
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
            },
        ]

    @staticmethod
    def _status_code(error: BaseException) -> int | None:
        value = getattr(error, "status_code", None)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @staticmethod
    def _provider_error_code(error: BaseException) -> str | None:
        body = getattr(error, "body", None)
        if not isinstance(body, dict):
            return None
        nested = body.get("error")
        candidates = (body.get("code"), nested.get("code") if isinstance(nested, dict) else None)
        return next(
            (
                value
                for value in candidates
                if isinstance(value, str) and _SAFE_PROVIDER_ERROR_CODE.fullmatch(value)
            ),
            None,
        )

    def _normalize_error(self, error: Exception) -> Exception:
        if isinstance(error, ProviderAdapterError):
            return error
        status_code = self._status_code(error)
        error_code = self._provider_error_code(error)
        if status_code == 429 and self.config.provider == _QWEN_PROVIDER:
            if error_code in _QWEN_PERMANENT_429_CODES:
                return PermanentProviderError(
                    f"provider request failed with non-recoverable code {error_code}"
                )
            if error_code not in _QWEN_TRANSIENT_429_CODES:
                suffix = f" code {error_code}" if error_code is not None else ""
                return PermanentProviderError(
                    f"provider request returned ambiguous Qwen HTTP 429{suffix}"
                )
        if status_code in {408, 409, 429} or (status_code is not None and status_code >= 500):
            return TransientProviderError(
                f"provider request failed with recoverable HTTP status {status_code}"
            )
        if status_code is not None:
            return PermanentProviderError(
                f"provider request failed with non-recoverable HTTP status {status_code}"
            )
        if isinstance(error, (TimeoutError, ConnectionError)):
            return TransientProviderError(f"provider transport failed: {type(error).__name__}")

        try:
            import openai
        except ImportError:
            openai = None  # type: ignore[assignment]
        if openai is not None and isinstance(
            error,
            (openai.APIConnectionError, openai.APITimeoutError),
        ):
            return TransientProviderError(f"provider transport failed: {type(error).__name__}")
        return ProviderAdapterError(f"provider client failed: {type(error).__name__}")

    def _record(
        self,
        *,
        task: Task,
        step_index: int,
        prompt_sha256: str,
        started: float,
        outcome: ProviderCallOutcome,
        response: object | None = None,
        error: BaseException | None = None,
        source_status_code: int | None = None,
        source_request_id: object = None,
        source_error_code: str | None = None,
    ) -> None:
        usage = _field(response, "usage") if response is not None else None
        choices = _field(response, "choices", ()) if response is not None else ()
        first_choice = choices[0] if isinstance(choices, (list, tuple)) and choices else None
        request_id = (
            _field(response, "_request_id", _field(response, "id"))
            if response is not None
            else source_request_id
        )
        record = ProviderCallRecord(
            run_id=self.run_id,
            task_id=task.task_id,
            step_index=step_index,
            adapter_name=self.name,
            provider=self.config.provider,
            requested_model=self.config.model,
            returned_model=(
                str(_field(response, "model"))
                if response is not None and _field(response, "model") is not None
                else None
            ),
            outcome=outcome,
            latency_ms=(time.perf_counter() - started) * 1000,
            prompt_sha256=prompt_sha256,
            prompt_version=_PROMPT_VERSION,
            request_config_sha256=request_config_sha256(self.config),
            input_tokens=_optional_nonnegative_int(_field(usage, "prompt_tokens")),
            output_tokens=_optional_nonnegative_int(_field(usage, "completion_tokens")),
            total_tokens=_optional_nonnegative_int(_field(usage, "total_tokens")),
            finish_reason=(
                str(_field(first_choice, "finish_reason"))
                if first_choice is not None and _field(first_choice, "finish_reason") is not None
                else None
            ),
            request_id_hash=_request_id_hash(request_id),
            status_code=(
                200 if response is not None else source_status_code if error is not None else None
            ),
            error_type=type(error).__name__ if error is not None else None,
            provider_error_code=source_error_code,
        )
        try:
            self.telemetry.record(record)
        except Exception:
            raise ProviderTelemetryError("provider telemetry sink failed") from None

    async def execute_step(
        self,
        task: Task,
        *,
        step_index: int,
        artifacts: tuple[Artifact, ...],
    ) -> Artifact:
        """Call the provider once and convert a valid response into one Artifact."""

        messages = self._prompt(task, step_index, artifacts)
        client = self._get_client()
        prompt_sha256 = hashlib.sha256(
            json.dumps(messages, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        started = time.perf_counter()
        response: object | None = None
        try:
            request: dict[str, object] = {
                "model": self.config.model,
                "messages": messages,
                "max_tokens": self.config.max_output_tokens,
                "temperature": self.config.temperature,
                "stream": False,
            }
            if self.config.seed is not None:
                request["seed"] = self.config.seed
            if self.config.enable_thinking is not None:
                request["extra_body"] = {"enable_thinking": self.config.enable_thinking}
            response = await client.chat.completions.create(
                **request,
            )
            choices = _field(response, "choices", ())
            if not isinstance(choices, (list, tuple)) or not choices:
                raise ProviderProtocolError("provider response did not contain a choice")
            first_choice = choices[0]
            finish_reason = _field(first_choice, "finish_reason")
            if finish_reason != "stop":
                raise ProviderProtocolError(
                    f"provider response did not finish normally: {finish_reason!r}"
                )
            message = _field(first_choice, "message")
            content = _field(message, "content")
            if not isinstance(content, str) or not content.strip():
                raise ProviderProtocolError("provider response content was empty or non-text")
        except asyncio.CancelledError as error:
            with suppress(ProviderTelemetryError):
                self._record(
                    task=task,
                    step_index=step_index,
                    prompt_sha256=prompt_sha256,
                    started=started,
                    outcome=ProviderCallOutcome.CANCELLED,
                    response=response,
                    error=error,
                )
            raise
        except Exception as error:
            normalized = self._normalize_error(error)
            if isinstance(normalized, ProviderProtocolError):
                outcome = ProviderCallOutcome.PROTOCOL_ERROR
            elif isinstance(normalized, RecoverableAgentError):
                outcome = ProviderCallOutcome.RECOVERABLE_ERROR
            else:
                outcome = ProviderCallOutcome.PERMANENT_ERROR
            self._record(
                task=task,
                step_index=step_index,
                prompt_sha256=prompt_sha256,
                started=started,
                outcome=outcome,
                response=response,
                error=normalized,
                source_status_code=self._status_code(error),
                source_request_id=getattr(error, "request_id", None),
                source_error_code=self._provider_error_code(error),
            )
            if normalized is error:
                raise
            raise normalized from None

        self._record(
            task=task,
            step_index=step_index,
            prompt_sha256=prompt_sha256,
            started=started,
            outcome=ProviderCallOutcome.SUCCEEDED,
            response=response,
        )
        return Artifact.create(
            task_id=task.task_id,
            step_index=step_index,
            producer=self.name,
            content=content,
            media_type="text/markdown",
        )
