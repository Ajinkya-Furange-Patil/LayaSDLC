Implement Stage 2 of LayaSDLC: a real, replaceable decision-engine adapter.

## Objective

Make the controller ask structured engineering questions and receive validated decisions from the actual Laya implementation.

## Requirements

1. Inspect the Stage 1 interfaces and the installed Laya documentation.
2. Implement only the inference path supported by the verified Laya version.
3. Define a versioned decision schema containing:
   - decision_id
   - task_id
   - decision_type
   - allowed_options
   - selected_option
   - confidence, only if meaningfully supported
   - rationale or supporting fields, only if supported
   - model identifier and version
   - latency and usage metrics when available
4. Support bounded decisions such as:
   - Task classification.
   - Workflow selection.
   - Retry versus escalation.
   - Context retrieval priority.
5. Validate every returned decision against the allowed schema and options.
6. Reject malformed, unsupported or out-of-scope outputs.
7. Add configurable timeouts and deterministic fallback behavior.
8. Never let a model-generated decision bypass tool permissions.
9. Make inference replaceable through a common interface.

## Testing

Test valid decisions, invalid outputs, timeouts, model failures, missing confidence information and unsupported decisions.

Use a fake decision engine for unit tests and a separate integration test for real Laya inference when available.

Do not simulate a successful real inference in the integration test.

## Acceptance criteria

- At least one real, bounded decision works through Laya.
- Invalid decisions are rejected safely.
- Fallback behavior is tested.
- Tests do not require paid inference.
- Actual latency and usage measurements are recorded when obtainable.

Do not add OpenCode event integration or autonomous code execution yet.