Implement Stage 3: the LayaSDLC workflow router.

## Objective

Convert a structured engineering task into a bounded next action without repeatedly asking a coding LLM to plan the entire workflow.

## Actions

Support these workflow actions:
- INSPECT_REPOSITORY
- RETRIEVE_CONTEXT
- IMPLEMENT_CHANGE
- RUN_TESTS
- REVIEW_DIFF
- ESCALATE
- REQUEST_APPROVAL
- COMPLETE

Use Laya to select among appropriate, pre-approved choices when suitable. Use deterministic rules to exclude invalid transitions and enforce mandatory checks.

## State machine

A task must have an explicit current state, allowed next states, action history and completion conditions.

Reject impossible transitions. A task cannot be marked COMPLETE merely because Laya selected COMPLETE.

## Routing policy

- Simple, deterministic tasks should avoid unnecessary LLM calls.
- Tasks requiring source changes should obtain relevant context first.
- High-risk or ambiguous tasks should request additional inspection or escalation.
- Failed tests should lead to diagnosis, a bounded retry or escalation.
- Repeated identical failures should not trigger infinite retries.
- Deployment and destructive actions require appropriate approval.

## Deliverables

Implement the routing policy, state-transition validator, unit tests and a CLI demonstration using mock tasks.

## Acceptance criteria

Demonstrate at least five scenarios, including a simple task, a bug fix, a failed test, an ambiguous task and a high-risk action.

Log why each route was chosen and which rules constrained it.

Do not execute real repository modifications yet. 