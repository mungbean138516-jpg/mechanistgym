"""Optional hosted-model adapters and sanitized call telemetry."""

from .openai_compatible import (
    PROMPT_VERSION,
    OpenAICompatibleAdapter,
    OpenAICompatibleConfig,
    PermanentProviderError,
    ProviderAdapterError,
    ProviderConfigurationError,
    ProviderProtocolError,
    ProviderTelemetryError,
    TransientProviderError,
    create_openai_compatible_client,
    request_config_sha256,
)
from .telemetry import (
    InMemoryProviderTelemetry,
    ProviderCallOutcome,
    ProviderCallRecord,
    ProviderTelemetrySink,
)

__all__ = [
    "InMemoryProviderTelemetry",
    "OpenAICompatibleAdapter",
    "OpenAICompatibleConfig",
    "PROMPT_VERSION",
    "PermanentProviderError",
    "ProviderAdapterError",
    "ProviderCallOutcome",
    "ProviderCallRecord",
    "ProviderConfigurationError",
    "ProviderProtocolError",
    "ProviderTelemetryError",
    "ProviderTelemetrySink",
    "TransientProviderError",
    "create_openai_compatible_client",
    "request_config_sha256",
]
