Implement Stage 4: persistent engineering state and context reuse.

## Objective

Allow tasks to resume without replaying the entire conversation or repeating completed analysis.

## Requirements

Use SQLite unless the existing architecture provides a justified alternative.

Persist:
- Task identifier and objective.
- Current workflow state.
- Relevant repository revision and working-tree status.
- Decisions and selected actions.
- Completed steps and outstanding questions.
- Evidence references, including test results.
- Model calls, latency and actual token usage when available.
- Retry count and failure history.

Store concise, structured engineering facts instead of unrestricted conversation transcripts wherever possible.

Distinguish:
- Verified facts.
- User requirements.
- Model hypotheses.
- Unresolved questions.
- Execution results.

Reuse previous context only when its validity can be established. Invalidate or refresh source summaries, test results and dependency information when relevant inputs change.

Do not store credentials, API keys or unnecessary sensitive data.

## Acceptance criteria

- A task survives service restarts.
- The workflow resumes from the last valid state.
- Repeated requests do not duplicate completed steps unnecessarily.
- Stale evidence is not treated as current.
- Database migrations and persistence tests work.

Add a CLI command to inspect the task state and its evidence.