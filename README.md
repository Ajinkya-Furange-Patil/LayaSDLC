# LayaSDLC

**A research-oriented, token-efficient controller that routes *bounded* engineering
decisions through the open-source [Laya] decision model inside an OpenCode
workflow.**

Laya never writes code here. It answers four small, closed questions — *what kind
of task is this, which workflow step next, retry or escalate, what context to
prioritise* — and a deterministic controller turns the answers into a validated,
versioned, auditable envelope. Anything the model cannot answer cleanly is
rejected and answered by a deterministic baseline instead.

> **Status: Stage 2 — decision-engine adapter.** Working, tested, honest about
> what is not built yet. See [`TASKS.md`](TASKS.md) for the live checklist.

---

## Verified capabilities

Everything in this section was **measured on this machine**, not assumed. Each
row links to where it is proven.

| # | Verified capability | Evidence |
|---|---|---|
| V1 | A real Laya endpoint answers `POST /v1/systemone` with HTTP 200 in ~0.55–0.85 s | `tests/integration/test_laya_real.py` |
| V2 | The service reports model identity and version (`laya-0.3.4/typed-decisions`) and per-call `usage` tokens | integration output, printed per run |
| V3 | **139 offline unit tests** and **7 integration tests** pass | `python -m pytest` |
| V4 | The decision service has **zero runtime dependencies** (stdlib only; `pytest` is the sole dev dependency) | `pyproject.toml` → `dependencies = []` |
| V5 | Four bounded decision types, each with a closed canonical option set | `contracts.py` → `DECISION_SPACE` |
| V6 | Malformed / unsupported / out-of-scope answers are **rejected**, never coerced | `validation.py`, `tests/test_validation.py` |
| V7 | Tool permissions are enforced **twice** — options are narrowed *before* any engine is called, and the validated envelope is re-checked after | `permissions.py`, `tests/test_permissions.py` |
| V8 | A deterministic fallback answers under the same confidence threshold, so "fallback" cannot launder an unconfident answer | `controller.py`, `tests/test_controller.py` |
| V9 | Destructive/deployment work is gated by **keyword matching**, never by a model output | `safety.py`, `tests/test_safety.py` |
| V10 | Latency and token usage are measured and recorded per decision; absent usage stays `null`, never `0` | `metrics.py`, `tests/test_health.py` |
| V11 | The engine is swappable behind one protocol — fake, deterministic, HTTP and (unavailable) SDK engines are all driven by the same controller | `engine.py` |

### Real-endpoint findings (discovered by testing, then fixed)

These are recorded because they are *surprising* and were reproducible:

1. **A single-option question always fails.** `POST /v1/systemone` returns
   HTTP `503 inference_unavailable` for *every* question offering exactly one
   option — all four decision types, all option contents, 5/5 attempts each —
   while two or more options return `200` (5/5). The controller therefore
   settles a collapsed option set from the permission policy (`source="policy"`)
   instead of padding the question with a fabricated option.
2. **The endpoint's own 503 says `"please retry"`** — and it was being raised
   *outside* the retry loop, so it was never retried. Interpretation now happens
   inside the loop; permanent refusals (400/422/401) still are not retried.
3. **`/health` reports `collecting_data: true`.** Do not send secrets,
   credentials or private data through the public endpoint.

---

## Planned features — **not built yet**

Nothing below exists. It is listed so nobody mistakes intent for implementation.

| Planned | Why it is not here |
|---|---|
| OpenCode event integration | Stage 2 explicitly excludes it |
| Autonomous code execution | Stage 2 explicitly excludes it |
| SQLite persistence | Stage 1 excludes it; metrics are in-memory only |
| Frontend / dashboard | Out of scope for these stages |
| Multi-agent orchestration | Out of scope for these stages |
| Local `laya` inference | **Blocked by hardware** — see below |
| Rationale text on decisions | Laya generates no text, so a rationale would be invented data |

### Why local Laya is not available on this host

Measured, not guessed (full reasoning in [`docs/adr/0001-environment-capability.md`](docs/adr/0001-environment-capability.md)):

* **7.6 GB RAM with ~1.9 GB free**, against ~1.3 GB *per resident checkpoint*
  plus a torch runtime.
* `laya-decision-api` declares `Requires-Python: >=3.11,<3.14`; this host runs
  **Python 3.14.3**.
* `torch 2.11.0+cu126` and `transformers 5.8.0` are already installed and CUDA
  works on the GTX 1650 (4 GB), but **the `laya` package itself is not
  installed** and no Laya weights are present.

So the primary path is the remote endpoint, and `LayaSdkEngine` ships as an
optional seam that **skips rather than pretending to work**.

---

## Quickstart

```bash
# offline suite — must always be green, no network needed
cd services/decision
python -m venv .venv && .venv/bin/pip install pytest
python -m pytest -m "not integration"

# real Laya — opt-in, sends real requests, never fakes a success
python -m pytest -m integration -s
```

Point at a different endpoint without touching code:

```bash
LAYA_BASE_URL=https://your-host python -m pytest -m integration
```

### Using the controller

```python
from layasdlc import (
    ControllerConfig, DeterministicEngine, LayaHttpEngine,
    TaskState, ToolPermissionPolicy, WorkflowController,
)

controller = WorkflowController(
    engine=LayaHttpEngine(base_url="https://laya.inference.zaitlabs.com"),
    config=ControllerConfig(timeout_s=10),
    fallback=DeterministicEngine(),          # deterministic baseline
    permissions=ToolPermissionPolicy.read_only(),   # never lets edit_code through
)

result = controller.decide(
    TaskState(task_id="T-1", subject="Checkout throws 500",
              body="Applying a promo code raises a 500; regression from pricing refactor."),
    "task_classification",
)

print(result.outcome)   # Outcome.DECIDED
print(result.source)    # "engine" | "fallback" | "policy"
print(result.envelope.to_dict())
```

`DecisionEnvelope` (`schema_version = "1.0"`) carries `decision_id`, `task_id`,
`decision_type`, `allowed_options`, `selected_option`, `confidence` (only when
meaningfully supported), `rationale` (`None` for Laya — it writes no text),
`model` / `model_version`, `latency_ms` and `usage`.

---

## Architecture

Five boundaries, deliberately kept apart:

| Module | Owns | Must never own |
|---|---|---|
| `engine.py` + `engines/` | How an answer is obtained | Whether an answer is allowed |
| `validation.py` | Whether an answer is well-formed and in scope | How it was produced |
| `permissions.py` | What tools a decision may name | Confidence thresholds |
| `controller.py` | Sequencing one decision end to end | Execution of anything |
| `metrics.py` / `health.py` | Recording what happened | Deciding anything |

Safety classification lives apart from all of the above because it is
deterministic and must never be influenced by a model.

More detail: [`docs/architecture.md`](docs/architecture.md).

---

## Security & data handling

* The default endpoint is a **public, free, keyless** service that reports
  `collecting_data: true`. Treat it as a postcard: **no secrets, tokens,
  credentials or private customer data.**
* Model output **never** widens tool access. `ToolPermissionPolicy` narrows the
  offered options before any request, and `guard_decision()` re-checks the
  validated envelope afterwards. The fallback engine is subject to the same
  check.
* Report vulnerabilities privately — see [`SECURITY.md`](SECURITY.md).

---

## Contributing

Contributions welcome. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) first — in
short: tick nothing in `TASKS.md` you have not actually proven, keep the offline
suite green, and never turn a planned capability into a claimed one.

---

## License

Apache-2.0 — see [`LICENSE`](LICENSE).

[Laya]: https://github.com/receptron/laya
