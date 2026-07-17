# Changelog

All notable changes to MechanistGym will be documented here.

## Unreleased

### Added

- M0 research-program framing and end-to-end lifecycle.
- Initial roadmap and issue-to-review protocol.
- Explicit Model, Environment, Agent, Verifier, Episode, and Trace contracts.
- First-order decay analytic fixture with independent verification.
- Experimental `mechanistgym.runtime` namespace with Task and Artifact types, recovery behavior, and
  persistent-store contracts; revisioned Checkpoints remain runtime-managed recovery metadata.
- SQLite-backed atomic checkpoints, deterministic failure injection, fallback rerouting, and
  close/reopen recovery tests.
- Recovery acceptance tests for async cancellation and abrupt OS-process termination followed by a
  fresh-process resume.
- `ExecutionSpec` and bounded `DurableRunner.run_many` execution across independent Tasks, with
  immutable adapter-chain snapshots, stable input-order results, per-Task Agent-failure isolation,
  and preservation of committed work during batch cancellation.
- Infrastructure-error admission control that lets active siblings settle, prevents queued Tasks
  from starting, and preserves multiple exceptional outcomes in a Python exception group.
- A deterministic async demonstration showing three Tasks, two active workflow slots, and one
  checkpointed fallback that does not interrupt its siblings.
- Product-first README that separates working runtime capabilities from future research directions.
