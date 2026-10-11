# LayaSDLC

**A research-oriented, token-efficient controller that routes *bounded* engineering
decisions through the open-source [Laya] decision model inside an OpenCode
workflow.**

Laya never writes code here. It answers four small, closed questions — *what kind
of task is this, which workflow step next, retry or escalate, what context to
prioritise* — and a deterministic controller turns the answers into a validated,
versioned, auditable envelope. Anything the model cannot answer cleanly is
rejected and answered by a deterministic baseline instead.

> **Status: Stage 8 — complete.** All eight stages implemented and tested.
> See [`TASKS.md`](TASKS.md) for the live checklist and
> [`docs/verification-report.md`](docs/verification-report.md) for evidence.

---

## Verified capabilities

Everything in this section was **measured on this machine**, not assumed.

| # | Verified capability | Evidence |
|---|---|---|
| V1 | A real Laya endpoint answers `POST /v1/systemone` with HTTP 200 | `tests/integration/test_laya_real.py` (7 tests) |
| V2 | The service reports model identity, version, and per-call `usage` tokens | Integration test output |
| V3 | **542 offline unit tests** and **7 integration tests** pass | `python -m pytest -m "not integration" -q` |
| V4 | The decision service has **zero runtime dependencies** (stdlib only) | `pyproject.toml` → `dependencies = []` |
| V5 | Four bounded decision types, each with a closed canonical option set | `contracts.py` → `DECISION_SPACE` |
| V6 | Malformed / unsupported / out-of-scope answers are **rejected**, never coerced | `validation.py`, `tests/test_validation.py` |
| V7 | Tool permissions are enforced **twice** — before and after the engine call | `permissions.py`, `tests/test_permissions.py` |
| V8 | A deterministic fallback answers under the same confidence threshold | `controller.py`, `tests/test_controller.py` |
| V9 | Destructive/deployment work is gated by **keyword matching**, never by a model | `safety.py`, `tests/test_safety.py` |
| V10 | Latency and token usage are recorded per decision; absent usage stays `null` | `metrics.py`, `tests/test_health.py` |
| V11 | The engine is swappable behind one protocol | `engine.py` — fake, deterministic, HTTP engines |
| V12 | Eight workflow actions with a full state machine and transition table | `workflow.py`, `tests/test_workflow.py` |
| V13 | Deterministic routing with 10 mandatory rules + bounded inference | `router.py`, `tests/test_router.py` |
| V14 | SQLite persistence with migrations, FK constraints, and staleness tracking | `store.py`, `tests/test_store.py` |
| V15 | OpenCode custom tools (`layasdlc_route`, `layasdlc_inspect`, `layasdlc_approve`) | `.opencode/tools/layasdlc.ts`, `.opencode/plugins/layasdlc.ts` |
| V16 | Code-aware context retrieval with deterministic ranking and budgeting | `context.py`, `tests/test_context.py` |
| V17 | Controlled execution with bounded retries and evidence recording | `execution.py`, `tests/test_execution.py` |
| V18 | Reproducible offline benchmark comparing three configurations | `benchmark.py`, `tests/test_benchmark.py` |

---

## Quickstart

```bash
# offline suite — must always be green, no network needed
cd services/decision
python -m venv .venv && .venv/bin/pip install pytest
python -m pytest -m "not integration" -q

# real Laya — opt-in, sends real requests, never fakes a success
python -m pytest -m integration -s
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
    fallback=DeterministicEngine(),
    permissions=ToolPermissionPolicy.read_only(),
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

### CLI

```bash
# Route a task
python -m layasdlc route --subject "Fix the crash" --kind bug_fix

# Run the demo scenarios
python -m layasdlc demo

# Inspect a persisted task
python -m layasdlc inspect --task-id T-1

# Run the offline benchmark
python -m layasdlc.benchmark run --repeat 1
```

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

Stage 3+ adds the workflow layer:

| Module | Owns |
|---|---|
| `workflow.py` | State machine, transitions, completion conditions |
| `router.py` | Deterministic routing policy with bounded inference |
| `store.py` | SQLite persistence, migrations, staleness |
| `context.py` | Code-aware context retrieval, ranking, budgeting |
| `execution.py` | Controlled execution, evidence recording |
| `coding.py` | Replaceable coding adapter protocol |
| `benchmark.py` | Reproducible evaluation harness |

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
* The SQLite store contains no credentials — a test enforces that no secret
  columns exist.
* The OpenCode plugin uses file-based JSON bridges; user input never reaches a
  shell command line.

---

## Limitations

* **Token savings are unproven.** The offline benchmark uses estimated token
  counts. Real provider measurements require a configured API key and live
  endpoint access. See [`docs/verification-report.md`](docs/verification-report.md).
* **Local Laya SDK is unavailable** on this host (Python 3.14 vs `<3.14`
  requirement, 1.9 GB free RAM). The HTTP endpoint is the primary path.
* **No frontend/dashboard.** CLI only.
* **No multi-agent orchestration.** Out of scope for Stages 0–8.
* **Context retrieval is line-based**, not AST-based for Python. Symbol search
  uses regex, not a full parser.

---

## Contributing

Contributions welcome. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) first — in
short: tick nothing in `TASKS.md` you have not actually proven, keep the offline
suite green, and never turn a planned capability into a claimed one.

---

## License

Apache-2.0 — see [`LICENSE`](LICENSE).

[Laya]: https://github.com/receptron/laya
