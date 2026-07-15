# Research Engineering Lifecycle

MechanistGym combines research design, research software engineering, benchmark development, and artifact review.

## 1. Problem formulation

State a falsifiable question, a credible null result, and a bounded scope.

**Gate:** a reviewer can identify which result would refute the hypothesis.

## 2. Protocol and preregistration

Freeze task splits, baselines, primary outcomes, budgets, stopping rules, and acceptance criteria before full evaluation.

**Gate:** the primary comparison cannot be silently changed after observing results.

## 3. Vertical-slice implementation

Implement the smallest end-to-end path with explicit interfaces and structured traces.

**M0 example:** observations → parameter estimate → prediction → independent verification.

**Gate:** the path compiles, runs, and exposes failure states.

## 4. Verification

Check that the implementation satisfies its specification.

**M0 example:** the analytic simulator matches the closed-form solution and an incorrect artifact is rejected.

**Gate:** positive and negative fixtures behave as specified.

## 5. Scientific validation

Check that the benchmark measures the intended capability rather than a shortcut or implementation artifact.

**Planned example:** introduce observation noise and topology shifts to test whether apparent success depends on noiseless algebra.

**Gate:** graders have gold fixtures, documented limitations, and leakage controls.

## 6. Evaluation and failure analysis

Run preregistered comparisons, quantify uncertainty, classify failures, and preserve null results.

**Gate:** every headline claim links to a configuration, manifest, evaluator, and reproducible artifact.

## 7. Internal review

Review scientific assumptions, software quality, privacy, licensing, statistics, and reproducibility through issues and pull requests.

**Gate:** high-risk assumptions are resolved or explicitly documented.

## 8. External reproduction

An independent reviewer reproduces primary results without private context.

**Gate:** discrepancies are resolved or recorded before release.

## 9. Release and maintenance

Tag and archive the exact code, task, evaluator, configuration, and report versions. Result-changing fixes require explicit release notes and re-evaluation.
