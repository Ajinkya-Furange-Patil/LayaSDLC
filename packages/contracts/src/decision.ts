/**
 * TypeScript mirror of `services/decision/src/layasdlc/contracts.py`.
 *
 * This is the OpenCode integration boundary: OpenCode is TypeScript, the
 * decision service is Python, and the envelope is the one place they must agree
 * exactly. Field names and their order are asserted to match by
 * `services/decision/tests/test_contract_parity.py`, so the two sides cannot
 * drift apart silently.
 *
 * Everything here is types and constants — no runtime dependencies, no I/O.
 */

/** Version of the decision schema. Must equal `contracts.SCHEMA_VERSION`. */
export const SCHEMA_VERSION = "1.1";

// ---------------------------------------------------------------------------------------
// Bounded decision types
// ---------------------------------------------------------------------------------------

/**
 * The four bounded decision spaces. The set is closed on purpose: an engine
 * asked for anything else is rejected before it is called, and an answer
 * outside the caller's option list is rejected after.
 */
export const DECISION_TYPES = [
  "task_classification",
  "workflow_selection",
  "retry_vs_escalate",
  "context_priority",
] as const;
export type DecisionType = (typeof DECISION_TYPES)[number];

/**
 * Canonical option set per decision type. A caller may narrow this but never
 * widen it — widening would let a request introduce an option the type does
 * not define, which is exactly the out-of-scope case the validator exists to
 * catch.
 */
export const DECISION_SPACE: Readonly<Record<DecisionType, readonly string[]>> = {
  task_classification: [
    "bug_fix",
    "feature",
    "refactor",
    "testing",
    "documentation",
    "investigation",
  ],
  // Workflow options double as tool identifiers, which is what lets
  // permissions gate them independently of the model.
  workflow_selection: ["edit_code", "run_tests", "read_investigate", "update_docs"],
  retry_vs_escalate: ["retry", "escalate"],
  context_priority: ["high", "medium", "low"],
};

// ---------------------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------------------

/** The six bounded engineering task classes. */
export const TASK_KINDS = [
  "bug_fix",
  "feature",
  "refactor",
  "testing",
  "documentation",
  "investigation",
] as const;
export type TaskKind = (typeof TASK_KINDS)[number];

/**
 * Confidence-gate outcome. Mirrors `laya.confidence.GATE_STATES`, which
 * deliberately has no "gate was not configured" member — that case is
 * represented as `null`, never as a fourth value.
 */
export const GATE_STATES = ["passed", "abstained", "unevaluated"] as const;
export type GateState = (typeof GATE_STATES)[number];

/** What the controller ended up doing with a request. */
export const OUTCOMES = ["decided", "fallback", "rejected", "failed"] as const;
export type Outcome = (typeof OUTCOMES)[number];

/**
 * Routing instruction only. Nothing is executed by this service.
 */
export const ACTIONS = ["proceed", "investigate", "escalate", "abstain"] as const;
export type Action = (typeof ACTIONS)[number];

export const SAFETY_CLASSES = ["safe", "destructive", "deployment"] as const;
export type SafetyClass = (typeof SAFETY_CLASSES)[number];

/** Whether a claimed result is backed by test evidence. */
export const VERIFICATION_STATES = ["unverified", "tests_passed", "tests_failed"] as const;
export type VerificationState = (typeof VERIFICATION_STATES)[number];

/**
 * Who actually answered. `engine` names the configured slot; `source` names the
 * origin of the answer, so "how often did the real model answer?" is read from
 * `source.engine`, not from the engine label.
 */
export const SOURCES = ["engine", "fallback", "policy"] as const;
export type DecisionSource = (typeof SOURCES)[number];

// ---------------------------------------------------------------------------------------
// Value objects
// ---------------------------------------------------------------------------------------

/**
 * Token accounting. Absent counters stay `null`; they are never defaulted to
 * `0`, because a stored `0` reads as "this was free" rather than "this was not
 * measured".
 *
 * Key set matches `dataclasses.asdict(Usage)` exactly — `available` is a
 * derived value on the Python side, not a stored field, so it is not repeated
 * on the wire.
 */
export interface Usage {
  input_tokens: number | null;
  output_tokens: number | null;
}

/**
 * One candidate option and its probability.
 *
 * Best-first ordering (ties broken by option name) is a property of the
 * `alternatives` list on {@link DecisionEnvelope}, not of a single entry.
 */
export interface Alternative {
  option: string;
  probability: number;
}

/** Proof that a claimed result actually passed tests. */
export interface Evidence {
  test_command: string;
  tests_passed: boolean;
  artifact: string | null;
  checked_at: string | null;
}

// ---------------------------------------------------------------------------------------
// The envelope
// ---------------------------------------------------------------------------------------

/**
 * The one shape crossing the Python/TypeScript boundary.
 *
 * Property order here must match `contracts.DecisionEnvelope` in Python — the
 * parity test compares both name and order.
 *
 * `alternatives` was appended for schema 1.1 and mirrors the Python field: a
 * nullable, best-first ranking of the probability distribution the engine
 * actually reported. It is `null`, never `[]`, when no distribution exists —
 * an empty list would read as "the model considered nothing and ranked
 * nothing", which is a different claim.
 */
export interface DecisionEnvelope {
  schema_version: string;
  decision_id: string;
  task_id: string;
  decision_type: string;
  allowed_options: readonly string[];
  selected_option: string;
  confidence: number | null;
  rationale: string | null;
  model: string | null;
  model_version: string | null;
  latency_ms: number | null;
  usage: Usage | null;
  alternatives: readonly Alternative[] | null;
}

/** What the caller submitted. */
export interface TaskState {
  task_id: string;
  subject: string;
  body: string;
  path: string | null;
  context: Record<string, unknown>;
}

/** The controller's full reply for one bounded decision. */
export interface ControllerResult {
  envelope: DecisionEnvelope | null;
  outcome: Outcome;
  action: Action;
  gate: GateState | null;
  threshold: number | null;
  engine: string;
  source: string;
  safety_class: SafetyClass;
  requires_approval: boolean;
  approval_reason: string | null;
  latency_ms: number;
  error: string | null;
  tool: string | null;
  evidence: Evidence | null;
}

// ---------------------------------------------------------------------------------------
// Runtime helpers
// ---------------------------------------------------------------------------------------

const ENVELOPE_FIELDS = [
  "schema_version",
  "decision_id",
  "task_id",
  "decision_type",
  "allowed_options",
  "selected_option",
  "confidence",
  "rationale",
  "model",
  "model_version",
  "latency_ms",
  "usage",
  "alternatives",
] as const satisfies readonly (keyof DecisionEnvelope)[];

const RESULT_FIELDS = [
  "envelope",
  "outcome",
  "action",
  "gate",
  "threshold",
  "engine",
  "source",
  "safety_class",
  "requires_approval",
  "approval_reason",
  "latency_ms",
  "error",
  "tool",
  "evidence",
] as const satisfies readonly (keyof ControllerResult)[];

/**
 * Field names in declaration order. Exported so the Python parity test can
 * compare them against `dataclasses.fields(DecisionEnvelope)` without
 * parsing TypeScript.
 */
export const DECISION_ENVELOPE_FIELDS: readonly string[] = ENVELOPE_FIELDS;
export const CONTROLLER_RESULT_FIELDS: readonly string[] = RESULT_FIELDS;

/**
 * Structural check that a value looks like an envelope.
 *
 * This validates *shape*, not truth: it cannot tell whether `selected_option`
 * is genuinely inside `allowed_options`. Authoritative validation happens in
 * Python (`layasdlc.validation`); this exists so a TypeScript caller can fail
 * fast at the boundary rather than downstream.
 */
export function isDecisionEnvelope(value: unknown): value is DecisionEnvelope {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  for (const field of ENVELOPE_FIELDS) {
    if (!(field in candidate)) return false;
  }
  if (typeof candidate["schema_version"] !== "string") return false;
  if (typeof candidate["decision_id"] !== "string") return false;
  if (typeof candidate["task_id"] !== "string") return false;
  if (typeof candidate["decision_type"] !== "string") return false;
  if (!Array.isArray(candidate["allowed_options"])) return false;
  if (typeof candidate["selected_option"] !== "string") return false;
  const confidence = candidate["confidence"];
  if (confidence !== null && typeof confidence !== "number") return false;
  if (typeof candidate["latency_ms"] !== "number" && candidate["latency_ms"] !== null) {
    return false;
  }
  const alternatives = candidate["alternatives"];
  if (alternatives !== null && !Array.isArray(alternatives)) return false;
  if (Array.isArray(alternatives)) {
    for (const entry of alternatives) {
      if (!isAlternative(entry)) return false;
    }
    // Best-first with ties broken by option name, matching Python's sort key
    // (-probability, option). An out-of-order list is rejected rather than
    // quietly re-sorted, so a tampered payload fails fast instead of being
    // repaired into something that looks authoritative.
    for (let i = 1; i < alternatives.length; i += 1) {
      const previous = alternatives[i - 1] as Alternative;
      const current = alternatives[i] as Alternative;
      if (
        current.probability > previous.probability ||
        (current.probability === previous.probability && current.option < previous.option)
      ) {
        return false;
      }
    }
  }
  return true;
}

/** Structural check for one alternative. Shape only — it cannot attest that the number came from a model. */
export function isAlternative(value: unknown): value is Alternative {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  if (typeof candidate["option"] !== "string" || candidate["option"].trim() === "") {
    return false;
  }
  const probability = candidate["probability"];
  if (typeof probability !== "number" || !Number.isFinite(probability)) return false;
  return probability >= 0 && probability <= 1;
}

/**
 * Whether a decision type is one this stage supports.
 *
 * Unknown types are a caller bug, not a runtime condition — the Python service
 * raises for them rather than silently coercing.
 */
export function isDecisionType(value: string): value is DecisionType {
  return (DECISION_TYPES as readonly string[]).includes(value);
}

/** Narrow an option list to the canonical set for `decisionType`. */
export function narrowToDecisionSpace(
  decisionType: DecisionType,
  options: readonly string[],
): readonly string[] {
  const canonical = DECISION_SPACE[decisionType];
  return options.filter((option) => canonical.includes(option));
}

/**
 * A decision whose option set has collapsed to exactly one element.
 *
 * Such a decision is settled from policy rather than by inference — there is
 * nothing left to infer. Kept here so the OpenCode side reports it the same way
 * the Python controller does (`source = "policy"`).
 */
export function isForcedChoice(envelope: DecisionEnvelope): boolean {
  return envelope.allowed_options.length === 1;
}
