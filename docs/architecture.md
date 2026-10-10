# Architecture

LayaSDLC separates *obtaining* an answer from *permitting* one. The controller
never asks a model what it is allowed to do, and the model never learns what it
is allowed to do beyond the options it was handed.

---

## The five boundaries

```
                          ┌──────────────────────────────┐
   TaskState ───────────► │        WorkflowController     │
   decision_type          │  1. resolve + validate options│
                          │  2. narrow to permitted tools │  ◄── permissions.py
                          │  3. safety scan (deterministic)
                          │  4. ask engine under timeout  │──┐
                          │  5. validate answer           │  │
                          │  6. confidence gate           │  │
                          │  7. fallback if refused       │  │
                          │  8. re-check permissions      │  │
                          │  9. record latency + usage    │  │
                          └───────────────┬───────────────┘  │
                                          │                  │
                              ControllerResult               │
                                          │                  │
                                          ▼                  ▼
                             ┌────────────────────────────────────────┐
                             │           DecisionEngine protocol       │
                             ├──────────┬────────────┬────────┬────────┤
                             │  Fake    │Deterministic│  HTTP  │  SDK   │
                             │ (tests)  │ (fallback)  │(Laya)  │(local) │
                             └──────────┴────────────┴────────┴────────┘
```

| Module | Owns | Must never own |
|---|---|---|
| `engine.py` + `engines/` | *How* an answer is obtained | Whether an answer is allowed |
| `validation.py` | Whether an answer is well-formed and in scope | How it was produced |
| `permissions.py` | What tools a decision may name | Confidence thresholds |
| `controller.py` | Sequencing exactly one decision | Executing anything |
| `metrics.py` / `health.py` | Recording what happened | Deciding anything |
| `safety.py` | Destructive/deployment classification | Any model output |

Keeping `safety.py` apart from everything else is deliberate: it is keyword
matching, it is deterministic, and it must never be influenced by a model.

---

## Stage 2 invariants

These are the rules the tests exist to defend.

1. **Versioned envelope.** Every decision is a `DecisionEnvelope` with
   `SCHEMA_VERSION` (`"1.1"`). No bare strings are returned to callers.
2. **Four bounded decision types.** `DECISION_SPACE` maps each type to a closed
   canonical option set; an option outside it is a programming error and raises.
3. **Confidence only when meaningful.** `None` is a real value meaning "not
   measured"; it is never defaulted to `0` or to `1`. Absent token usage behaves
   the same way. `alternatives` follows the same rule: the engine's distribution
   is passed through in best-first order with ties broken by option name, and an
   engine that reported none gets `null` — never `[]`, which would claim the
   model ranked nothing. A malformed distribution is rejected, never repaired.
4. **Reject, do not coerce.** Malformed, unsupported and out-of-scope answers
   raise `DecisionRejected` subclasses and produce `Outcome.REJECTED`.
5. **Deterministic fallback under the same threshold.** A fallback cannot launder
   an unconfident answer, because the gate is evaluated identically both times.
6. **Tool permissions are enforced twice.**
   * **Layer 1 — before any engine call.** `narrow_options()` removes every tool
     the policy does not permit, so the model is never even offered them.
   * **Layer 2 — after validation.** `guard_decision()` re-checks the envelope,
     because an engine may return something outside the set it was given.
   * The fallback engine is subject to the same checks.
7. **Failures never escape `decide()`.** Engine problems become `Outcome.FAILED`
   with a typed reason. Caller mistakes (unknown decision type, option outside
   the canonical set) *do* raise, because silently accepting them would defeat
   the validator.

---

## Outcomes and what they mean

| Outcome | Meaning |
|---|---|
| `DECIDED` | A validated answer cleared the confidence gate |
| `FALLBACK` | The engine's answer was refused; the deterministic baseline answered instead |
| `REJECTED` | An answer arrived but was malformed, unsupported, out of scope, or too uncertain — and no fallback was enabled or able to help |
| `FAILED` | No answer arrived at all: timeout, transport error, or the engine raised |

`ControllerResult.source` says **who** answered:

| `source` | Meaning |
|---|---|
| `engine` | The configured decision engine |
| `fallback` | The deterministic baseline |
| `policy` | No inference — the option set had already collapsed to one permitted tool |

`metrics` records `source.*` counters for exactly this reason: `engine.*` names
the *configured slot*, so "how often did the real model answer?" is only
answerable from `source.engine`.

---

## A choice among one is not a decision

When permission narrowing leaves exactly two or more options, the engine is
consulted. When it leaves exactly **one**, the controller settles it from policy
(`source="policy"`) and does not call an engine at all.

Two independent justifications:

* **Logically:** the permission policy is the only thing that determined the
  answer. Asking a model would dress a constraint up as a judgement. The
  envelope's `confidence` is therefore `1.0` *by construction* — "certain
  because there was no alternative", not "the model felt sure".
* **Empirically:** the real endpoint returns HTTP `503 inference_unavailable`
  for every single-option question (all four decision types, 5/5 attempts each)
  while returning `200` for two or more.

The answer still passes through `validation.validate_answer()`, and layer 2 still
reviews the resulting envelope — so nothing about the contract is bypassed.

---

## Engine replaceability

`DecisionEngine` is a `runtime_checkable` Protocol: `name`, `version`,
`available()` and `decide(request) -> EngineAnswer`. Any object satisfying it
plugs in without touching the controller.

| Engine | Purpose | Network | Installed here |
|---|---|---|---|
| `FakeEngine` | Scripted unit-test answers | no | n/a |
| `DeterministicEngine` | Keyword baseline + fallback | no | always |
| `LayaHttpEngine` | Real Laya over `POST /v1/systemone` | yes | endpoint reachable |
| `LayaSdkEngine` | Real Laya via the local `laya` package | no | **no** — skips |

---

## Timeout model

```
EngineRequest.timeout_s   total budget for obtaining an answer
  └─ per attempt = (timeout_s - planned backoff) / attempts   [engine]
ControllerConfig.timeout_s + 1.0s                              [watchdog backstop]
```

The transport's own timeout is *sliced* so retries cannot overrun the caller's
budget. The watchdog waits slightly longer on purpose: it exists to catch engines
that ignore `timeout_s` entirely, and if it fired first it would mask the real
cause behind a generic "did not answer" message.

---

## Testing strategy

| Layer | How | Network |
|---|---|---|
| Unit | `FakeEngine`, injected `Transport`, `sleep=lambda s: None` | never |
| Integration | `LayaHttpEngine` against a real endpoint | yes, opt-in |

Rules:

* The integration module **never fabricates a success.** Either Laya answers, or
  the test skips with the real error attached.
* A degraded endpoint (503/timeout/429) skips; a defect in *this repo*
  (validation, permissions, contract) fails the test.

```bash
python -m pytest -m "not integration"   # offline, always green
python -m pytest -m integration         # real Laya
```
