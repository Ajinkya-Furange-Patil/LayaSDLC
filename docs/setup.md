# LayaSDLC Setup Guide

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | >= 3.11 | Stdlib only; no runtime dependencies |
| pytest | >= 8.0 | Dev dependency for running tests |
| Git | Any recent version | Required for context retrieval and evidence provenance |
| Node.js | >= 18 | Only for TypeScript contract build |
| OpenCode | v2.x | Only for the OpenCode integration |

**Hardware:** No special requirements. The deterministic offline path runs on any
machine. The remote Laya endpoint requires network access but no local GPU.

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/Ajinkya-Furange-Patil/LayaSDLC.git
cd LayaSDLC
```

### 2. Create a virtual environment

```bash
cd services/decision
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# or: .venv\Scripts\activate  # Windows
```

### 3. Install dev dependencies

```bash
pip install pytest
```

That is the **only** dependency. The decision service is stdlib-only
(`sqlite3`, `urllib`, `json`, `dataclasses`, `enum`).

### 4. Verify installation

```bash
python -m pytest -m "not integration" -q
```

Expected output: all tests pass (500+ tests).

---

## Configuration

### Environment variables

Copy the example file and edit:

```bash
cp .env.example .env
```

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `LAYA_BASE_URL` | `https://laya.inference.zaitlabs.com` | No | Laya inference endpoint |
| `LAYA_API_KEY` | (empty) | No | Bearer token for authenticated endpoints |
| `LAYA_MODEL` | (empty) | No | Model hint: `laya`, `laya/english`, `laya/multilingual`, `laya/typed-decisions`, `laya/watt-flash-0.1`, `typesafe/jev` |
| `LAYA_ENGINE` | `http` | No | `http` for remote endpoint, `sdk` for local (not available on all hosts) |
| `LAYA_PROBE_TIMEOUT` | `10` | No | Seconds to wait for live health probe |

### Privacy notice

The default Laya endpoint reports `collecting_data: true`. **Never send secrets,
credentials, tokens or private customer data through it.** The endpoint receives
only the task subject, body and path — no repository contents, no file contents,
no environment variables.

To run fully offline with no external calls:

```bash
# Use the deterministic engine only
LAYA_ENGINE=deterministic python -m layasdlc route --subject "Fix the crash" --kind bug_fix
```

---

## Running Tests

### Offline unit tests (always green, no network)

```bash
cd services/decision
python -m pytest -m "not integration" -q
```

### Integration tests (require live Laya endpoint)

```bash
python -m pytest -m integration -q
```

These tests make real HTTP requests to the Laya endpoint. They are opt-in and
will skip if the endpoint is unreachable.

### TypeScript contract build

```bash
cd packages/contracts
npm run build
```

---

## Using LayaSDLC

### CLI

```bash
# Route a task
python -m layasdlc route --subject "Fix the crash" --kind bug_fix

# Run the demo scenarios
python -m layasdlc demo

# Inspect a persisted task
python -m layasdlc inspect --task-id T-1 --store .layasdlc.sqlite3

# Run the offline benchmark
python -m layasdlc.benchmark run --repeat 1
```

### Python API

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
    TaskState(task_id="T-1", subject="Checkout throws 500"),
    "task_classification",
)
print(result.outcome, result.source, result.action)
```

### OpenCode integration

Place `.opencode/plugins/layasdlc.ts` and `.opencode/tools/layasdlc.ts` in your
project root. OpenCode will load them automatically. Configure permissions in
`opencode.json`:

```json
{
  "permission": {
    "layasdlc_route": "ask",
    "layasdlc_inspect": "allow",
    "layasdlc_approve": "ask"
  }
}
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError: No module named 'layasdlc'` | Package not on PYTHONPATH | Run from `services/decision` with `PYTHONPATH=src` |
| Integration tests skip | Endpoint unreachable | Check network; set `LAYA_BASE_URL` |
| `EngineTimeout` | Endpoint slow | Increase `LAYA_PROBE_TIMEOUT` or use deterministic engine |
| `StoreError: unable to open database` | Permission denied on SQLite file | Check write access to `.layasdlc.sqlite3` |
| TypeScript build fails | `node_modules` missing | Run `npm install` in `packages/contracts` |

---

## Cleanup

```bash
# Remove virtual environment
rm -rf services/decision/.venv

# Remove test caches
rm -rf services/decision/.pytest_cache
rm -rf services/decision/src/layasdlc/__pycache__
rm -rf services/decision/tests/__pycache__

# Remove SQLite stores
rm -f .layasdlc.sqlite3
```

---

## Project Structure

```
LayaSDLC/
├── services/decision/          # Python decision service
│   ├── src/layasdlc/           # Source modules
│   │   ├── contracts.py        # Typed contracts, schema
│   │   ├── controller.py       # Decision orchestration
│   │   ├── engine.py           # Engine protocol
│   │   ├── engines/            # Engine implementations
│   │   ├── permissions.py      # Tool permission policy
│   │   ├── safety.py           # Deterministic safety scan
│   │   ├── validation.py       # Answer validation
│   │   ├── workflow.py         # Stage 3 state machine
│   │   ├── router.py           # Stage 3 routing
│   │   ├── store.py            # Stage 4 persistence
│   │   ├── opencode_bridge.py  # Stage 5 bridge
│   │   ├── context.py          # Stage 6 context engineering
│   │   ├── execution.py        # Stage 7 execution
│   │   ├── coding.py           # Stage 7 coding adapter
│   │   └── benchmark.py        # Stage 8 evaluation
│   └── tests/                  # Test suite
├── packages/contracts/         # TypeScript contract mirror
├── .opencode/                  # OpenCode integration
├── Stages/                     # Stage specifications
├── docs/                       # Documentation
└── TASKS.md                    # Live checklist
```
