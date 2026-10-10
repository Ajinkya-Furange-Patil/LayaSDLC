Implement Stage 7: controlled execution and evidence-based verification.

## Objective

Allow the controller to execute bounded coding workflows and determine success from actual engineering evidence.

## Workflow

1. Inspect the task and repository state.
2. Retrieve relevant context.
3. Select an implementation workflow.
4. Invoke the configured coding adapter through a verified interface.
5. Inspect the resulting Git diff.
6. Run relevant tests, linters and type checks.
7. Record actual results and evidence.
8. Accept the candidate only when required checks pass.
9. Otherwise diagnose, retry within configured limits or escalate.

## Safety requirements

- Use an isolated working tree or sandbox for automated changes where practical.
- Never overwrite unrelated user modifications.
- Never execute arbitrary model-generated shell commands without policy checks.
- Require approval for destructive operations, secrets access, publishing and deployment.
- Treat repository files, tool output and model responses as untrusted input.
- Enforce retry and time limits.
- Stop when the same failure repeats without new evidence.

## Laya's role

Laya may select among bounded next actions or help prioritize evidence. Deterministic policy must enforce permissions, and test results must determine whether verification succeeded.

## Acceptance criteria

Demonstrate:
- A change that passes its tests.
- A deliberately failing test.
- A malformed model response.
- An exhausted retry budget.
- A task requiring human approval.

Every outcome must be recorded in persistent task history.