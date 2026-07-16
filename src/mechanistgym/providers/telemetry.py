"""Privacy-conscious telemetry for hosted model calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable


class ProviderCallOutcome(StrEnum):
    """Terminal outcome of one visible provider request."""

    SUCCEEDED = "succeeded"
    RECOVERABLE_ERROR = "recoverable_error"
    PERMANENT_ERROR = "permanent_error"
    PROTOCOL_ERROR = "protocol_error"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ProviderCallRecord:
    """Sanitized measurements for one provider request.

    Raw prompts, responses, authorization headers, and API keys are deliberately absent.
    Unknown token usage remains ``None`` rather than being reported as zero.
    """

    run_id: str
    task_id: str
    step_index: int
    adapter_name: str
    provider: str
    requested_model: str
    returned_model: str | None
    outcome: ProviderCallOutcome
    latency_ms: float
    prompt_sha256: str
    prompt_version: str
    request_config_sha256: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    finish_reason: str | None = None
    request_id_hash: str | None = None
    status_code: int | None = None
    error_type: str | None = None
    provider_error_code: str | None = None

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.step_index < 0:
            raise ValueError("step_index must be non-negative")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")
        if len(self.prompt_sha256) != 64:
            raise ValueError("prompt_sha256 must be a SHA-256 hex digest")
        if len(self.request_config_sha256) != 64:
            raise ValueError("request_config_sha256 must be a SHA-256 hex digest")
        for value in (self.input_tokens, self.output_tokens, self.total_tokens):
            if value is not None and value < 0:
                raise ValueError("token counts must be non-negative when known")


@runtime_checkable
class ProviderTelemetrySink(Protocol):
    """Destination for sanitized provider-call records."""

    def record(self, call: ProviderCallRecord) -> None:
        """Store one completed call record without blocking the event loop."""


@dataclass
class InMemoryProviderTelemetry:
    """Simple event-loop-local telemetry sink used by R2 evaluation."""

    _records: list[ProviderCallRecord] = field(default_factory=list, init=False, repr=False)

    def record(self, call: ProviderCallRecord) -> None:
        """Append one immutable call record."""

        self._records.append(call)

    @property
    def records(self) -> tuple[ProviderCallRecord, ...]:
        """Return an immutable snapshot in completion order."""

        return tuple(self._records)
