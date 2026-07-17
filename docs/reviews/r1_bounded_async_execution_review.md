# R1 Bounded Async Execution Acceptance Review

**Review type:** Verification and Validation (V&V) Review  
**Review date:** 2026-07-16  
**Decision:** Accepted for R1 local and remote verification. Independent external reproduction
remains pending.

## Scope reviewed

- immutable `ExecutionSpec` batch entries;
- immutable, preflight-validated Agent-chain snapshots;
- positive per-batch whole-Task concurrency limit;
- sequential execution and checkpoint recovery inside each Task;
- input-order result stability;
- terminal Agent-failure isolation;
- infrastructure-error admission control and lossless exception reporting;
- batch cancellation and later Recovery;
- deterministic installed-package demonstration.

## Acceptance evidence

| Requirement | Evidence | Result |
|---|---|---|
| Independent Tasks overlap | event-gated adapters enter two Tasks before either is released | Pass |
| Per-batch bound is enforced | observed active workflows never exceed `max_concurrency=2` | Pass |
| Results preserve input order | A, B, C returned in input order despite controlled release order | Pass |
| Terminal Agent failure is isolated | failed result returned while an active sibling completes | Pass |
| Failed execution releases its slot | queued healthy Task starts with `max_concurrency=1` | Pass |
| Recovery state is Task-local | one Task reroutes at step 1; sibling has no recovery events | Pass |
| Cancellation preserves committed work | active Task reopens at step 1; queued Task never starts | Pass |
| Invalid batches make no store mutations | invalid bound, ID, Task, and adapter-chain inputs fail preflight | Pass |
| Adapter chains are immutable during execution | mutable list and generator inputs execute from a tuple snapshot | Pass |
| Infrastructure failure controls admission | active sibling settles; queued Task never creates store state | Pass |
| Multiple child errors remain visible | two store errors and child self-cancellation plus store error form exception groups | Pass |
| Public async demo is deterministic | three Tasks, two active slots, only B uses fallback | Pass |
| Public demo cannot hang on reused state | non-empty database path fails explicitly | Pass |
| Existing R0 and scientific tests remain compatible | complete local test suite | Pass |
| Source passes local quality gates | compile, Ruff lint, Ruff format | Pass |
| Built package works outside the source tree | wheel install and async-demo smoke test | Pass |
| Python 3.11–3.13 remote matrix for commit `8ccd09c` | [GitHub Actions run 29482971109](https://github.com/mungbean138516-jpg/mechanistgym/actions/runs/29482971109) | Pass |
| Independent reproduction | External reviewer | Pending |

## Commands reviewed

```bash
make runtime-async-demo
make test
ruff check src tests
ruff format --check src tests
python -m pip wheel . --no-deps --no-build-isolation
```

Local result: 39 tests passed, including 13 deterministic R1 concurrency tests, 19 R0 runtime tests,
and all 7 pre-existing scientific tests. Ruff lint and format checks passed. The installed wheel ran
the bounded async demonstration from outside the repository source tree. GitHub Actions reproduced
the installation, package smoke tests, and quality gates on Python 3.11, 3.12, and 3.13.

## Observed async trace

```text
max_concurrency:     2
observed_max_active: 2
result_order:        [batch-a, batch-b, batch-c]
statuses:            all succeeded
recovered:           batch-b only
fallback_calls:      [(batch-b, 1)]
```

Task B's step 0 is committed before its injected step-1 failure. Its fallback starts at step 1 while
the other Tasks retain separate state and continue under the same batch limit.

## Review findings resolved before local acceptance

Independent API, code, and test reviews identified and the implementation resolved:

- mutable or generator-based failover chains changing after preflight;
- malformed adapters creating persisted Task state before failing;
- a reused async-demo database stranding its two-entry concurrency barrier;
- ambiguous infrastructure-error behavior for queued Tasks;
- multiple active exceptions being reduced to only one visible error;
- documentation implying a runtime-global or provider-level concurrency bound;
- documentation overstating Agent-failure isolation and cancellation recovery.

## Validation boundary

R1 verifies deterministic single-process concurrency semantics. It does **not** establish throughput,
latency, token-cost, or reliability improvements with real model providers. It does not provide
parallel DAG steps, provider rate limiting, automatic re-entrancy protection for shared adapters,
distributed workers, cross-batch Task claims, fair scheduling, priorities, or learned routing. The
next product-validation gate requires a real adapter and a matched sequential baseline.
