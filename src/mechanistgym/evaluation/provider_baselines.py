"""Matched engineering evaluation for visible provider recovery costs."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import math
import os
import re
import tempfile
import time
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from mechanistgym.providers import (
    PROMPT_VERSION,
    InMemoryProviderTelemetry,
    OpenAICompatibleAdapter,
    OpenAICompatibleConfig,
    ProviderCallOutcome,
    ProviderCallRecord,
    ProviderConfigurationError,
    create_openai_compatible_client,
    request_config_sha256,
)
from mechanistgym.runtime import (
    AgentAdapter,
    Artifact,
    DurableRunner,
    ExecutionFailed,
    RecoverableAgentError,
    SQLiteRuntimeStore,
    Task,
)


class BaselineCondition(StrEnum):
    """Conditions in one matched R2 engineering block."""

    SEQUENTIAL = "sequential_no_checkpoint"
    CHECKPOINT_CLEAN = "checkpoint_no_failure"
    CHECKPOINT_RESUME = "checkpoint_resume"
    RESTART_FROM_SCRATCH = "restart_from_scratch"


DEFAULT_CONDITION_ORDER = (
    BaselineCondition.SEQUENTIAL,
    BaselineCondition.CHECKPOINT_CLEAN,
    BaselineCondition.CHECKPOINT_RESUME,
    BaselineCondition.RESTART_FROM_SCRATCH,
)

_SAFE_EXPERIMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_SAFE_PUBLIC_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_QWEN_PROVIDER = "alibaba-model-studio"


class EndpointRegion(StrEnum):
    """Documented public region labels safe to include in exported reports."""

    BEIJING = "beijing"
    HONG_KONG = "hong-kong"
    SINGAPORE = "singapore"
    TOKYO = "tokyo"
    FRANKFURT = "frankfurt"
    US_VIRGINIA = "us-virginia"
    LOCAL_TEST = "local-test"
    UNDISCLOSED = "undisclosed"


_QWEN_REGION_HOST_SIGNATURES: dict[EndpointRegion, tuple[str, ...]] = {
    EndpointRegion.BEIJING: (
        "dashscope.aliyuncs.com",
        ".cn-beijing.maas.aliyuncs.com",
    ),
    EndpointRegion.HONG_KONG: (
        "cn-hongkong.dashscope.aliyuncs.com",
        ".cn-hongkong.maas.aliyuncs.com",
    ),
    EndpointRegion.SINGAPORE: (
        "dashscope-intl.aliyuncs.com",
        ".ap-southeast-1.maas.aliyuncs.com",
    ),
    EndpointRegion.TOKYO: (".ap-northeast-1.maas.aliyuncs.com",),
    EndpointRegion.FRANKFURT: (".eu-central-1.maas.aliyuncs.com",),
    EndpointRegion.US_VIRGINIA: ("dashscope-us.aliyuncs.com",),
}


def _validate_endpoint_region(
    config: OpenAICompatibleConfig,
    endpoint_region: EndpointRegion,
) -> None:
    if config.provider != _QWEN_PROVIDER:
        return
    signatures = _QWEN_REGION_HOST_SIGNATURES.get(endpoint_region)
    host = (urlsplit(config.base_url).hostname or "").lower()
    if signatures is None or not any(
        host == signature or (signature.startswith(".") and host.endswith(signature))
        for signature in signatures
    ):
        raise ValueError("Qwen endpoint host does not match endpoint_region")


def _task_definition_sha256(task: Task) -> str:
    payload = {
        "task_id": task.task_id,
        "objective": task.objective,
        "steps": task.steps,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ProviderBenchmarkManifest:
    """Sanitized immutable settings needed to audit a matched block."""

    provider: str
    requested_model: str
    endpoint_sha256: str
    endpoint_region: EndpointRegion
    timeout_seconds: float
    temperature: float
    seed: int | None
    max_output_tokens: int
    enable_thinking: bool | None
    prompt_version: str
    request_config_sha256: str
    task_definition_sha256: str
    condition_order: tuple[BaselineCondition, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not isinstance(self.requested_model, str):
            raise TypeError("provider and requested_model must be strings")
        if not self.provider.strip() or not self.requested_model.strip():
            raise ValueError("provider and requested_model must not be empty")
        object.__setattr__(self, "endpoint_region", EndpointRegion(self.endpoint_region))
        normalized_order = tuple(BaselineCondition(value) for value in self.condition_order)
        object.__setattr__(self, "condition_order", normalized_order)
        if (
            len(self.endpoint_sha256) != 64
            or len(self.request_config_sha256) != 64
            or len(self.task_definition_sha256) != 64
        ):
            raise ValueError("manifest hashes must be SHA-256 hex digests")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        if self.enable_thinking is not None and not isinstance(self.enable_thinking, bool):
            raise TypeError("enable_thinking must be None or a boolean")
        if len(self.condition_order) != len(DEFAULT_CONDITION_ORDER) or set(
            self.condition_order
        ) != set(DEFAULT_CONDITION_ORDER):
            raise ValueError("condition_order must contain every R2 condition exactly once")

    @classmethod
    def from_config(
        cls,
        config: OpenAICompatibleConfig,
        task: Task,
        *,
        endpoint_region: EndpointRegion,
        condition_order: Sequence[BaselineCondition] = DEFAULT_CONDITION_ORDER,
    ) -> ProviderBenchmarkManifest:
        """Hash endpoint and Task details while retaining reproducibility settings."""

        endpoint_region = EndpointRegion(endpoint_region)
        _validate_endpoint_region(config, endpoint_region)

        return cls(
            provider=config.provider,
            requested_model=config.model,
            endpoint_sha256=hashlib.sha256(config.base_url.rstrip("/").encode("utf-8")).hexdigest(),
            endpoint_region=endpoint_region,
            timeout_seconds=config.timeout_seconds,
            temperature=config.temperature,
            seed=config.seed,
            max_output_tokens=config.max_output_tokens,
            enable_thinking=config.enable_thinking,
            prompt_version=PROMPT_VERSION,
            request_config_sha256=request_config_sha256(config),
            task_definition_sha256=_task_definition_sha256(task),
            condition_order=tuple(condition_order),
        )


@dataclass(frozen=True, slots=True)
class PricingSnapshot:
    """User-supplied token prices for a simple estimate, never an invoice."""

    snapshot_id: str
    model: str
    endpoint_region: EndpointRegion
    token_tier: str
    input_usd_per_million: float
    output_usd_per_million: float
    currency: str = "USD"

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, str) or not isinstance(self.model, str):
            raise TypeError("snapshot_id and model must be strings")
        if not _SAFE_PUBLIC_TOKEN.fullmatch(self.snapshot_id):
            raise ValueError("snapshot_id must be a short public identifier")
        if (
            not self.model.strip()
            or len(self.model) > 128
            or any(character.isspace() for character in self.model)
        ):
            raise ValueError("model must be a non-empty public model identifier")
        object.__setattr__(self, "endpoint_region", EndpointRegion(self.endpoint_region))
        if not isinstance(self.token_tier, str) or not _SAFE_PUBLIC_TOKEN.fullmatch(
            self.token_tier
        ):
            raise ValueError("token_tier must be a short public identifier")
        if self.currency != "USD":
            raise ValueError("R2 price estimates currently support USD only")
        for value in (self.input_usd_per_million, self.output_usd_per_million):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError("token prices must be finite numbers")
            if not math.isfinite(value) or value < 0:
                raise ValueError("token prices must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class ConditionMetrics:
    """Measurements derived from provider records and observed Artifacts."""

    condition: BaselineCondition
    completed: bool
    verification_passed: bool
    provider_calls: int
    successful_provider_calls: int
    duplicated_provider_calls: int
    pre_failure_committed_steps: int
    recomputed_committed_steps: int
    preserved_committed_steps: int
    prefix_checksums_match: bool | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    estimated_cost_usd: float | None
    wall_time_ms: float
    provider_time_ms: float
    artifact_checksums: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MatchedBaselineReport:
    """One self-contained, sanitized engineering comparison."""

    schema_version: str
    experiment_id: str
    task_id: str
    step_count: int
    failure_step: int
    failure_injection: str
    manifest: ProviderBenchmarkManifest
    pricing: PricingSnapshot | None
    conditions: tuple[ConditionMetrics, ...]
    calls: tuple[ProviderCallRecord, ...]

    def to_json(self) -> str:
        """Serialize the report without prompts, responses, endpoint text, or secrets."""

        return json.dumps(asdict(self), ensure_ascii=False, indent=2, allow_nan=False)


class AdapterFactory(Protocol):
    """Create adapter identities backed by the same matched provider configuration."""

    def __call__(self, *, name: str, run_id: str) -> AgentAdapter:
        """Return an adapter whose sanitized records use ``run_id``."""


Verifier = Callable[[Task, tuple[Artifact, ...]], bool]


class _InjectedPostResponseFailure(RecoverableAgentError):
    """Controlled benchmark failure, distinct from an organic provider failure."""


class _FailAfterResponseOnce:
    """Lose one completed provider response before its Artifact can commit."""

    def __init__(self, delegate: AgentAdapter, *, failure_step: int) -> None:
        self.delegate = delegate
        self.failure_step = failure_step
        self.failed = False
        self.name = delegate.name

    async def execute_step(
        self,
        task: Task,
        *,
        step_index: int,
        artifacts: tuple[Artifact, ...],
    ) -> Artifact:
        artifact = await self.delegate.execute_step(
            task,
            step_index=step_index,
            artifacts=artifacts,
        )
        if step_index == self.failure_step and not self.failed:
            self.failed = True
            raise _InjectedPostResponseFailure(
                "injected post-response failure before Artifact commit"
            )
        return artifact


def _validate_artifact(
    artifact: object,
    *,
    task: Task,
    step_index: int,
    producer: str,
) -> Artifact:
    if not isinstance(artifact, Artifact):
        raise TypeError("adapter did not return an Artifact")
    if artifact.artifact_id != f"{task.task_id}.step-{step_index}":
        raise ValueError("adapter returned a non-canonical artifact_id")
    if artifact.task_id != task.task_id or artifact.step_index != step_index:
        raise ValueError("adapter returned an Artifact for the wrong task step")
    if artifact.producer != producer:
        raise ValueError("adapter returned an Artifact with the wrong producer")
    return artifact


async def _run_plain(task: Task, adapter: AgentAdapter) -> tuple[Artifact, ...]:
    artifacts: list[Artifact] = []
    for step_index in range(len(task.steps)):
        candidate = await adapter.execute_step(
            task,
            step_index=step_index,
            artifacts=tuple(artifacts),
        )
        artifacts.append(
            _validate_artifact(
                candidate,
                task=task,
                step_index=step_index,
                producer=adapter.name,
            )
        )
    return tuple(artifacts)


async def _close_adapters(adapters: Sequence[AgentAdapter]) -> None:
    awaitables = []
    errors: list[BaseException] = []
    for adapter in adapters:
        close = getattr(adapter, "aclose", None)
        if close is None:
            continue
        try:
            outcome = close()
        except BaseException as error:
            errors.append(error)
            continue
        if inspect.isawaitable(outcome):
            awaitables.append(outcome)
    if awaitables:
        settled = await asyncio.gather(*awaitables, return_exceptions=True)
        errors.extend(outcome for outcome in settled if isinstance(outcome, BaseException))
    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise BaseExceptionGroup("multiple provider adapters failed to close", errors)


def _known_sum(records: tuple[ProviderCallRecord, ...], field: str) -> int | None:
    values = [getattr(record, field) for record in records]
    if not values or any(value is None for value in values):
        return None
    return sum(values)


def _structural_verifier(task: Task, artifacts: tuple[Artifact, ...]) -> bool:
    return (
        len(artifacts) == len(task.steps)
        and all(artifact.step_index == index for index, artifact in enumerate(artifacts))
        and all(artifact.content.strip() for artifact in artifacts)
    )


def _expected_step_counts(
    condition: BaselineCondition,
    *,
    step_count: int,
    failure_step: int,
) -> Counter[int]:
    counts: Counter[int] = Counter({step: 1 for step in range(step_count)})
    if condition is BaselineCondition.CHECKPOINT_RESUME:
        counts[failure_step] += 1
    elif condition is BaselineCondition.RESTART_FROM_SCRATCH:
        for step in range(failure_step + 1):
            counts[step] += 1
    return counts


def _validate_condition_call_evidence(
    *,
    condition: BaselineCondition,
    run_id: str,
    records: tuple[ProviderCallRecord, ...],
    manifest: ProviderBenchmarkManifest,
    task: Task,
    failure_step: int,
) -> tuple[ProviderCallRecord, ...]:
    """Reject a nominally completed block whose provider evidence is absent or mismatched."""

    calls = tuple(
        record for record in records if record.run_id == run_id and record.task_id == task.task_id
    )
    expected_steps = _expected_step_counts(
        condition,
        step_count=len(task.steps),
        failure_step=failure_step,
    )
    observed_steps = Counter(record.step_index for record in calls)
    if observed_steps != expected_steps:
        raise RuntimeError(
            f"provider telemetry for {condition.value} does not match the controlled call protocol"
        )
    for record in calls:
        if record.outcome is not ProviderCallOutcome.SUCCEEDED:
            raise RuntimeError(
                f"provider telemetry for {condition.value} contains a non-successful request"
            )
        if (
            record.provider != manifest.provider
            or record.requested_model != manifest.requested_model
            or record.prompt_version != manifest.prompt_version
            or record.request_config_sha256 != manifest.request_config_sha256
        ):
            raise RuntimeError(
                f"provider telemetry for {condition.value} does not match the benchmark manifest"
            )
    return calls


def _metrics(
    *,
    condition: BaselineCondition,
    run_id: str,
    records: tuple[ProviderCallRecord, ...],
    artifacts: tuple[Artifact, ...],
    pre_failure_artifacts: tuple[Artifact, ...],
    task: Task,
    wall_time_ms: float,
    verifier: Verifier,
    pricing: PricingSnapshot | None,
) -> ConditionMetrics:
    calls = tuple(
        record for record in records if record.run_id == run_id and record.task_id == task.task_id
    )
    successes = tuple(record for record in calls if record.outcome is ProviderCallOutcome.SUCCEEDED)
    step_counts = Counter(record.step_index for record in calls)
    duplicated_provider_calls = sum(max(0, count - 1) for count in step_counts.values())

    final_by_step = {artifact.step_index: artifact for artifact in artifacts}
    recomputed = sum(step_counts[prefix.step_index] > 1 for prefix in pre_failure_artifacts)
    preserved = sum(
        step_counts[prefix.step_index] == 1
        and final_by_step.get(prefix.step_index) is not None
        and final_by_step[prefix.step_index].checksum == prefix.checksum
        for prefix in pre_failure_artifacts
    )
    prefix_match = None
    if pre_failure_artifacts:
        prefix_match = all(
            final_by_step.get(prefix.step_index) is not None
            and final_by_step[prefix.step_index].checksum == prefix.checksum
            for prefix in pre_failure_artifacts
        )

    input_tokens = _known_sum(calls, "input_tokens")
    output_tokens = _known_sum(calls, "output_tokens")
    total_tokens = _known_sum(calls, "total_tokens")
    estimated_cost = None
    if pricing is not None and input_tokens is not None and output_tokens is not None:
        estimated_cost = (
            input_tokens * pricing.input_usd_per_million
            + output_tokens * pricing.output_usd_per_million
        ) / 1_000_000

    return ConditionMetrics(
        condition=condition,
        completed=len(artifacts) == len(task.steps),
        verification_passed=verifier(task, artifacts),
        provider_calls=len(calls),
        successful_provider_calls=len(successes),
        duplicated_provider_calls=duplicated_provider_calls,
        pre_failure_committed_steps=len(pre_failure_artifacts),
        recomputed_committed_steps=recomputed,
        preserved_committed_steps=preserved,
        prefix_checksums_match=prefix_match,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=estimated_cost,
        wall_time_ms=wall_time_ms,
        provider_time_ms=sum(record.latency_ms for record in calls),
        artifact_checksums=tuple(artifact.checksum for artifact in artifacts),
    )


async def run_matched_provider_baselines(
    task: Task,
    *,
    adapter_factory: AdapterFactory,
    telemetry: InMemoryProviderTelemetry,
    manifest: ProviderBenchmarkManifest,
    failure_step: int,
    pricing: PricingSnapshot | None = None,
    verifier: Verifier = _structural_verifier,
    experiment_id: str | None = None,
    database_directory: Path | None = None,
) -> MatchedBaselineReport:
    """Run one matched engineering block and retain sanitized call-level evidence.

    The failure is injected after a provider response but before Artifact commit. The checkpoint
    condition closes and reopens the same SQLite store; the restart condition opens a fresh store.
    Both remain in one Python process, so this is not an abrupt-process-outage experiment.
    """

    if isinstance(failure_step, bool) or not isinstance(failure_step, int):
        raise TypeError("failure_step must be an integer")
    if not 0 <= failure_step < len(task.steps):
        raise ValueError("failure_step must identify one configured Task step")
    if manifest.task_definition_sha256 != _task_definition_sha256(task):
        raise ValueError("manifest does not match the supplied Task definition")
    if pricing is not None and (
        pricing.model != manifest.requested_model
        or pricing.endpoint_region != manifest.endpoint_region
    ):
        raise ValueError("pricing snapshot does not match the benchmark model and region")
    experiment_id = experiment_id or uuid.uuid4().hex
    if not isinstance(experiment_id, str) or not _SAFE_EXPERIMENT_ID.fullmatch(experiment_id):
        raise ValueError("experiment_id must be a safe 1-96 character identifier")
    run_ids = {f"{experiment_id}:{condition.value}" for condition in manifest.condition_order}
    initial_records = telemetry.records
    if any(record.run_id in run_ids for record in initial_records):
        raise ValueError("telemetry already contains records for this experiment_id")

    conditions: list[ConditionMetrics] = []
    created_adapters: list[AgentAdapter] = []

    def create(condition: BaselineCondition, role: str) -> AgentAdapter:
        run_id = f"{experiment_id}:{condition.value}"
        adapter = adapter_factory(name=f"{condition.value}-{role}", run_id=run_id)
        created_adapters.append(adapter)
        return adapter

    async def checkpoint_clean(database: Path) -> tuple[tuple[Artifact, ...], tuple[Artifact, ...]]:
        worker = create(BaselineCondition.CHECKPOINT_CLEAN, "worker")
        with SQLiteRuntimeStore(database) as store:
            result = await DurableRunner(store).run(task, (worker,))
        return result.artifacts, ()

    async def failure_condition(
        condition: BaselineCondition,
        first_database: Path,
        final_database: Path,
    ) -> tuple[tuple[Artifact, ...], tuple[Artifact, ...]]:
        primary = create(condition, "primary")
        fallback = create(condition, "fallback")
        faulting = _FailAfterResponseOnce(primary, failure_step=failure_step)
        try:
            with SQLiteRuntimeStore(first_database) as store:
                await DurableRunner(store).run(task, (faulting,))
        except ExecutionFailed as failure:
            pre_failure_artifacts = failure.result.artifacts
        else:
            raise AssertionError("failure condition did not terminate its first execution")
        if not faulting.failed:
            raise RuntimeError(
                "controlled failure did not occur; an organic provider failure changed the path"
            )
        if len(pre_failure_artifacts) != failure_step:
            raise RuntimeError("pre-failure checkpoint does not match the injected failure step")
        with SQLiteRuntimeStore(final_database) as store:
            result = await DurableRunner(store).run(task, (fallback,))
        return result.artifacts, pre_failure_artifacts

    if database_directory is None:
        temporary_directory = tempfile.TemporaryDirectory()
        base_directory = Path(temporary_directory.name)
    else:
        temporary_directory = None
        base_directory = database_directory
        base_directory.mkdir(parents=True, exist_ok=True)

    try:
        for condition in manifest.condition_order:
            run_id = f"{experiment_id}:{condition.value}"
            started = time.perf_counter()
            if condition is BaselineCondition.SEQUENTIAL:
                worker = create(condition, "worker")
                artifacts = await _run_plain(task, worker)
                pre_failure_artifacts: tuple[Artifact, ...] = ()
            elif condition is BaselineCondition.CHECKPOINT_CLEAN:
                database = base_directory / f"{experiment_id}-checkpoint-clean.sqlite3"
                if database.exists():
                    raise FileExistsError(f"benchmark database already exists: {database}")
                artifacts, pre_failure_artifacts = await checkpoint_clean(database)
            elif condition is BaselineCondition.CHECKPOINT_RESUME:
                database = base_directory / f"{experiment_id}-checkpoint-resume.sqlite3"
                if database.exists():
                    raise FileExistsError(f"benchmark database already exists: {database}")
                artifacts, pre_failure_artifacts = await failure_condition(
                    condition,
                    database,
                    database,
                )
            else:
                failed_database = base_directory / f"{experiment_id}-restart-failed.sqlite3"
                fresh_database = base_directory / f"{experiment_id}-restart-fresh.sqlite3"
                if failed_database.exists() or fresh_database.exists():
                    raise FileExistsError("restart benchmark database already exists")
                artifacts, pre_failure_artifacts = await failure_condition(
                    condition,
                    failed_database,
                    fresh_database,
                )
            wall_time_ms = (time.perf_counter() - started) * 1000
            current_records = telemetry.records[len(initial_records) :]
            _validate_condition_call_evidence(
                condition=condition,
                run_id=run_id,
                records=current_records,
                manifest=manifest,
                task=task,
                failure_step=failure_step,
            )
            conditions.append(
                _metrics(
                    condition=condition,
                    run_id=run_id,
                    records=current_records,
                    artifacts=artifacts,
                    pre_failure_artifacts=pre_failure_artifacts,
                    task=task,
                    wall_time_ms=wall_time_ms,
                    verifier=verifier,
                    pricing=pricing,
                )
            )
    finally:
        try:
            await _close_adapters(created_adapters)
        finally:
            if temporary_directory is not None:
                temporary_directory.cleanup()

    calls = tuple(
        record
        for record in telemetry.records[len(initial_records) :]
        if record.run_id in run_ids and record.task_id == task.task_id
    )
    return MatchedBaselineReport(
        schema_version="mechanistgym.provider-baseline.v2",
        experiment_id=experiment_id,
        task_id=task.task_id,
        step_count=len(task.steps),
        failure_step=failure_step,
        failure_injection="post_response_pre_commit_graceful_reopen",
        manifest=manifest,
        pricing=pricing,
        conditions=tuple(conditions),
        calls=calls,
    )


def _demo_task() -> Task:
    return Task(
        task_id="qwen-provider-baseline",
        objective="Prepare a concise reliability review for a resumable AI workflow.",
        steps=(
            "State the user-visible failure scenario and relevant constraints.",
            "Identify three technical risks and one mitigation for each.",
            "Write a verification checklist with measurable acceptance criteria.",
        ),
    )


async def _run_live(arguments: argparse.Namespace) -> MatchedBaselineReport:
    task = _demo_task()
    config = OpenAICompatibleConfig.qwen_model_studio_from_env()
    region_value = os.getenv("DASHSCOPE_REGION")
    if not region_value:
        raise ProviderConfigurationError(
            "DASHSCOPE_REGION is required so the report can validate the endpoint host"
        )
    telemetry = InMemoryProviderTelemetry()
    condition_order = tuple(BaselineCondition(value) for value in arguments.condition_order)
    manifest = ProviderBenchmarkManifest.from_config(
        config,
        task,
        endpoint_region=EndpointRegion(region_value),
        condition_order=condition_order,
    )

    pricing_values = (
        arguments.price_snapshot,
        arguments.price_token_tier,
        arguments.input_price,
        arguments.output_price,
    )
    if any(value is not None for value in pricing_values) and not all(
        value is not None for value in pricing_values
    ):
        raise ValueError(
            "--price-snapshot, --price-token-tier, --input-price, and --output-price "
            "must be supplied together"
        )
    pricing = None
    if all(value is not None for value in pricing_values):
        pricing = PricingSnapshot(
            snapshot_id=arguments.price_snapshot,
            model=config.model,
            endpoint_region=manifest.endpoint_region,
            token_tier=arguments.price_token_tier,
            input_usd_per_million=arguments.input_price,
            output_usd_per_million=arguments.output_price,
        )
    client = create_openai_compatible_client(config)

    def factory(*, name: str, run_id: str) -> AgentAdapter:
        return OpenAICompatibleAdapter(
            name=name,
            config=config,
            run_id=run_id,
            telemetry=telemetry,
            client=client,
        )

    try:
        return await run_matched_provider_baselines(
            task,
            adapter_factory=factory,
            telemetry=telemetry,
            manifest=manifest,
            failure_step=arguments.failure_step,
            pricing=pricing,
        )
    finally:
        await client.close()


def main() -> None:
    """Run the explicit opt-in live Qwen engineering smoke block."""

    parser = argparse.ArgumentParser(
        description="Run four matched conditions (15 requests with the default settings)."
    )
    parser.add_argument(
        "--confirm-live-calls",
        action="store_true",
        help="acknowledge that this command sends billable hosted-model requests",
    )
    parser.add_argument("--failure-step", type=int, default=1)
    parser.add_argument(
        "--condition-order",
        nargs=4,
        choices=[condition.value for condition in BaselineCondition],
        default=[condition.value for condition in DEFAULT_CONDITION_ORDER],
        metavar="CONDITION",
        help="one occurrence of every condition; rotate across repeated empirical blocks",
    )
    parser.add_argument("--price-snapshot")
    parser.add_argument(
        "--price-token-tier",
        help="short public tier ID, such as up-to-32k; serialized into the report",
    )
    parser.add_argument("--input-price", type=float)
    parser.add_argument("--output-price", type=float)
    arguments = parser.parse_args()
    if not arguments.confirm_live_calls:
        parser.error("--confirm-live-calls is required; no provider request was sent")
    print(asyncio.run(_run_live(arguments)).to_json())


if __name__ == "__main__":
    main()
