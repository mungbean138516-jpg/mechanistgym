## Summary

Describe the change in plain language and link the issue it addresses (`Closes #...`).

## Research rationale

- Research question or engineering invariant:
- Hypothesis or expected behavior:
- Scope intentionally excluded:

## Change type

- [ ] Research design or benchmark specification
- [ ] Agent, skill, curriculum, or orchestration implementation
- [ ] Verifier or evaluation implementation
- [ ] Test, infrastructure, or documentation improvement
- [ ] Bug fix that may affect reported results

## Evidence

List the commands run and summarize their results. Attach only reproducible, non-sensitive
artifacts. For empirical changes, report the baseline, fixed budget, uncertainty, and known
failure cases.

```text
make compile
make test
```

## Scientific validity and reproducibility

- [ ] Inputs, versions, random seeds, and configuration are recorded.
- [ ] Train/development/held-out boundaries remain intact.
- [ ] The comparison uses the same model, tool, token, time, and compute budget where applicable.
- [ ] New claims are supported by an executable verifier or clearly documented human review.
- [ ] Negative and null results are reported rather than filtered out.

## Software quality

- [ ] Tests cover the new behavior and a relevant failure mode.
- [ ] Existing tests pass locally.
- [ ] Public interfaces, assumptions, and limitations are documented.
- [ ] No secrets, credentials, private data, or large generated artifacts are committed.
- [ ] Backward-incompatible changes and result-changing bug fixes are called out explicitly.

## Reviewer focus

Identify the highest-risk assumption, file, or result that deserves close review.
