# ADR-0002: Laya inference path — HTTP first, local SDK optional

- **Status:** Accepted
- **Date:** 2026-10-10
- **Decides:** how this project talks to Laya, and which engine is primary

## Context

ADR-0001 ruled out a local install. That leaves the question of *how* to reach a
real Laya endpoint without guessing at its API.

Two candidate paid endpoints were also found (`https://layahost.com/v1/systemone`
and `https://api.laya.studio/v1/systemone`), both requiring an API key (HTTP 401
without one). The free keyless endpoint was preferred so contributors can run
the integration suite without credentials.

## Decision

1. **`LayaHttpEngine` is primary**, speaking `POST /v1/systemone`.
2. **`LayaSdkEngine` is optional** — present, correct, and skipped when the
   `laya` package is missing.
3. **`FakeEngine` and `DeterministicEngine` satisfy the same `DecisionEngine`
   protocol**, so the controller is never modified to swap engines.

## Verified wire protocol

Captured from a live endpoint before any integration code was written:

```
POST /v1/systemone
{"state": <str|obj>, "questions": {"selection": {...}}, "model": "<optional>"}

200 {"model":"laya-0.3.4/typed-decisions",
     "answers":{"selection":{"type":"choice","choice":"...",
                             "confidence":0.3114,
                             "probabilities":{...}}},
     "usage":{"input_tokens":237,"output_tokens":0}}
400 {"detail":[{"loc":[...],"msg":"...","type":"unknown_model"}]}
422 {"detail":[{"loc":[...],"msg":"...","type":"value_error"}]}
401/403 credentials refused · 429 rate limited · 5xx unavailable
connection/DNS failure -> EngineUnavailable · timeout -> EngineTimeout
```

**Accepted model names:** `laya`,
`laya/{english,multilingual,typed-decisions,watt-flash-0.1}`, `typesafe/jev`.
**Not accepted:** `laya-english` → HTTP 400 `unknown_model` (verified directly,
and asserted by an integration test).

**Question types** are exactly `choice`, `score`, `noul`.

## Consequences

* **`rationale` is always `None` from a Laya engine.** Laya generates no text;
  writing a sentence would be inventing data the model did not produce.
* **Confidence is `max(probabilities)`** (Laya's `answer_confidence`), *not* the
  entropy field named `confidence` in the raw payload. They mean different
  things and only the former answers "how sure is the choice".
* **Retries** apply to transient conditions only (timeout, 5xx, 429).
  Interpretation runs *inside* the retry loop because the endpoint's 503 body
  literally says `"please retry"` — raised outside it, that instruction was
  never acted on. 400/422/401 are permanent and are never retried.
* **The per-attempt timeout is a slice of the caller's total budget**, not the
  whole budget, so retries cannot overrun the controller's watchdog.
* **Single-option questions are settled by policy, not by the endpoint**, because
  the endpoint returns HTTP 503 for them (see `README.md` → *Real-endpoint
  findings*).

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Local `laya` package | ADR-0001: out of RAM, Python `<3.14` constraint |
| Paid endpoints (`layahost.com`, `api.laya.studio`) | Require API keys; would block contributors from running the integration suite |
| Synthesise a rationale | Laya writes no text; that would be fabricated data |
| Fabricate an option to avoid the single-option 503 | Inventing data to satisfy a model is exactly what this project refuses to do |
