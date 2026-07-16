# R0 Checkpointed Failover Acceptance Review

**Review type:** Verification and Validation (V&V) Review
**Review date:** 2026-07-16
**Decision:** Accepted for the local R0 vertical slice; remote CI and external reproduction remain
pending.

## Scope reviewed

- immutable Task definition and ordered step boundary;
- application-level immutable Artifact with SHA-256 content validation;
- revisioned Checkpoint with exact Artifact references;
- SQLite atomic Artifact–Checkpoint commit;
- ordered AgentAdapter failover chain;
- deterministic recoverable and non-recoverable failures;
- close/reopen and abrupt-interruption recovery;
- structured append-only execution trace;
- installed-package runtime demonstration.

## Acceptance evidence

| Requirement | Evidence | Result |
|---|---|---|
| Completed work is not repeated after failover | `primary=[0, 1]`, `fallback=[1, 2]` | Pass |
| State survives runner/store recreation | SQLite close/reopen acceptance test | Pass |
| Abrupt interruption can reopen from committed state | task remains `RUNNING`, revision 1 reloads | Pass |
| Artifact and Checkpoint commit atomically | injected SQLite trigger rolls both changes back | Pass |
| Stale checkpoints cannot overwrite new state | revision conflict test | Pass |
| Terminal state cannot regress through a stale writer | compare-and-swap status test | Pass |
| Invalid output can fail over | protocol-violation acceptance test | Pass |
| Programming errors do not silently fail over | non-recoverable exception test | Pass |
| Failed recovery is not labeled recovered | exhausted failover-chain test | Pass |
| Persisted content corruption is detected | SHA-256 mismatch test | Pass |
| Existing scientific fixture remains compatible | original decay tests and demo | Pass |
| Source passes local quality gates | compile, Ruff lint, Ruff format | Pass |
| Built package works outside the source tree | wheel install and runtime smoke test | Pass |
| Python 3.11–3.13 remote matrix | GitHub Actions | Pending push/PR |
| Independent reproduction | External reviewer | Pending |

## Commands reviewed

```bash
make runtime-demo
make check
python -m pip wheel . --no-deps --no-build-isolation
```

Local result: 24 tests passed, including 17 runtime-specific tests and all 7 pre-existing scientific
tests. Ruff lint and format checks passed. The built wheel imported and completed the runtime demo
from outside the repository source tree.

## Observed recovery trace

```text
task.created
task.started
attempt.started          # primary step 0
artifact.committed
checkpoint.saved         # revision 1
attempt.started          # primary step 1
agent.failed
step.rerouted            # fallback starts at step 1
attempt.started
artifact.committed
checkpoint.saved         # revision 2
recovery.completed
attempt.started          # fallback step 2
artifact.committed
checkpoint.saved         # revision 3
task.completed
```

The trace shows that step 0 was committed once. The fallback begins at step 1.

## Review findings resolved before acceptance

Independent code/API/test reviews identified and the implementation resolved:

- a task-ID boundary that could produce an invalid canonical Artifact ID;
- a false `recovered=True` result on terminal failure;
- a stale status-write race that could regress a terminal task;
- commits attempted while pending or past the final step;
- store corruption being misclassified as an Agent failure;
- reroute events missing structured step and fallback-agent fields;
- `RECOVERING` remaining as stale history rather than current lifecycle state;
- missing abrupt-interruption and transaction-rollback acceptance tests.

## Validation boundary

R0 verifies deterministic local execution semantics. It does **not** yet establish improvement on
real model APIs, token cost, wall-clock latency, or end-task quality. It does not recover hidden model
reasoning or uncommitted external side effects. The next validation gate is a real adapter plus a
matched restart-from-scratch baseline reporting duplicated work, recovered work, latency, and final
result equivalence.
