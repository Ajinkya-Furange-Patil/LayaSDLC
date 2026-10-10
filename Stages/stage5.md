Implement Stage 5: connect LayaSDLC to OpenCode.

## Objective

Let a developer initiate and observe a controlled software engineering workflow from OpenCode.

## Before coding

Inspect the installed OpenCode version and official documentation. Verify the supported plugin hooks, tool interfaces, permissions and model invocation mechanisms.

Do not assume an API exists merely because it appears in an example for another version.

## Requirements

1. Implement the smallest supported integration, preferably a custom tool or plugin.
2. Accept a developer task and create a persistent task record.
3. Send compact structured task state to the controller.
4. Return the next permitted action and a concise explanation.
5. Let the controller request repository inspection, context retrieval, implementation, tests or escalation.
6. Keep coding-model invocation behind a replaceable adapter.
7. Use supported OpenCode interfaces rather than scraping terminal output or relying on undocumented internals.
8. Apply least-privilege tool permissions.
9. Log workflow transitions and actual model usage when available.
10. Provide a safe way to cancel a task and inspect its progress.

Initially, require confirmation before executing repository-changing operations.

## Acceptance criteria

Demonstrate one end-to-end workflow initiated from OpenCode, using a mock coding adapter if necessary.

The workflow must create a task, obtain a decision, return a valid action, record the result and display the current state.

Do not add automatic deployment, unrestricted shell execution or parallel autonomous agents.