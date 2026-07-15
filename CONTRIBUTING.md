# Contributing and Review Protocol

MechanistGym uses an issue-to-evidence workflow.

## Development lifecycle

1. Open a research or engineering issue.
2. State the hypothesis, concrete example, acceptance criteria, and non-goals.
3. Record material design decisions in **docs/decisions/**.
4. Create a focused branch.
5. Implement the smallest testable change.
6. Add or update technical documentation and executable examples.
7. Run unit, integration, and regression checks.
8. Open a pull request that links the issue and evidence.
9. Review scientific assumptions, code, tests, data governance, and reproducibility.
10. Merge only after the acceptance criteria pass.

## Definition of Done

A capability is not done merely because code runs. It is done when:

- its scientific and software contracts are defined;
- a concrete systems-biology use case is documented;
- the implementation matches the definition;
- a test would fail if the implementation were wrong;
- assumptions, limitations, and failure modes are documented;
- the result can be reproduced from a clean environment.

## Commit discipline

Use meaningful commits that capture real decisions. Do not split changes to manufacture activity or contribution-graph history.

Suggested prefixes:

- **research:** hypothesis, protocol, or analysis decision
- **feat:** new capability
- **test:** verification or regression evidence
- **fix:** defect correction
- **docs:** technical or reproducibility documentation
- **refactor:** behavior-preserving structure change
- **release:** versioned milestone

## AI-assisted development

AI assistance is allowed, but the contributor remains responsible for every merged line. A pull request must state material AI assistance and confirm that the author:

- read and understood the implementation;
- ran the checks;
- verified scientific assumptions;
- can explain the failure modes;
- did not include private or restricted data.
