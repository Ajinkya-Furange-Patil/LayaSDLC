# LayaSDLC Implementation Audit

**Date:** 2026-01-16
**Auditor:** Automated inspection of the repository at commit `b497bf3`

---

## Executive Summary

The repository has **substantial implementation** across all eight stages. Core
decision-engine, routing, persistence, context engineering, execution, and benchmark
modules exist with tests. However, several critical gaps remain:

1. **README.md is badly outdated** — claims "Stage 2" when Stage 8 is complete
2. **No `docs/setup.md`** — explicitly required by Stage 1 and the operating contract
3. **Benchmark uses only estimated tokens** — violates the requirement to use real provider measurements
4. **No real-provider benchmarking path** — required by Stage 8 acceptance criteria
5. **No `docs/verification-report.md`** — required by the operating contract
6. **Local Laya SDK option in `.env.example` is misleading** — the SDK cannot run on this host

---

## Stage-by-Stage Status

### Stage 1 — Foundation and Reproducibility

| Task | Status | Evidence |
|------|--------|----------|
| 1.1 Environment report | VERIFIED WORKING | `docs/adr/0001-environment-capability.md` |
| 1.2 Local Laya feasibility | VERIFIED WORKING | ADR-0001: hardware/Python constraints documented |
| 1.3 Official Laya docs verified | VERIFIED WORKING | Integration tests pass against live endpoint |
| 1.4 Five separations | VERIFIED WORKING | `contracts.py`, `controller.py`, `permissions.py`, `metrics.py`, `workflow.py` |
| 1.5 README, ADRs, `.env.example` | PARTIALLY WORKING | README exists but is **stale** (says Stage 2, wrong test count) |
| 1.6 Typed contracts | VERIFIED WORKING | `contracts.py` imports cleanly, TS parity test passes |
| 1.7 Health check | VERIFIED WORKING | `health.py` returns JSON with engine/fallback status |
| 1.8 Test config, `.gitignore`, manifests | VERIFIED WORKING | `pyproject.toml`, `.gitignore` present |
| 1.9 README verified/planned split | BROKEN | README lists OpenCode integration and SQLite as "not built yet" — both are built |
| 1.10 `docs/setup.md` | **NOT IMPLEMENTED** | File does not exist |

**Required repairs:**
- [ ] Rewrite README to reflect actual Stage 8 status and current test count (542+)
- [ ] Create `docs/setup.md` with prerequisites, installation, configuration, testing, troubleshooting
- [ ] Remove stale "Planned features" section

---

### Stage 2 — Decision Engine

| Task | Status | Evidence |
|------|--------|----------|
| 2.1 Versioned schema | VERIFIED WORKING | `SCHEMA_VERSION = "1.1"`, `DecisionEnvelope` with 13 fields |
| 2.2 Four bounded decisions | VERIFIED WORKING | `DECISION_SPACE` with 4 types |
| 2.3 Validate every answer | VERIFIED WORKING | `validation.py` with `validate_answer()` |
| 2.4 Reject malformed/out-of-scope | VERIFIED WORKING | `tests/test_validation.py`, `tests/test_probability_integrity.py` |
| 2.5 Timeouts + deterministic fallback | VERIFIED WORKING | `ControllerConfig.timeout_s`, `DeterministicEngine` |
| 2.6 Permission enforcement (twice) | VERIFIED WORKING | `narrow_options()` + `guard_decision()` |
| 2.7 Replaceable engine | VERIFIED WORKING | `DecisionEngine` protocol, 4 implementations |
| 2.8 Fake engine for tests | VERIFIED WORKING | `FakeEngine` in `engines/fake.py` |
| 2.9 Real-endpoint findings fed back | VERIFIED WORKING | Retry loop fix, single-option policy, watchdog |
| 2.10 Probability distribution preserved | VERIFIED WORKING | `Alternative` class, `alternatives` field, integrity tests |

**No repairs required.** This stage is solid.

---

### Stage 3 — Workflow Router and State Machine

| Task | Status | Evidence |
|------|--------|----------|
| 3.1 Eight workflow actions | VERIFIED WORKING | `WorkflowAction` enum with 8 members |
| 3.2 Task state machine | VERIFIED WORKING | `WorkflowTask` with phase, history, evidence, retries |
| 3.3 Transition validator | VERIFIED WORKING | `validate_transition()`, `TRANSITIONS` table |
| 3.4 Routing policy | VERIFIED WORKING | `WorkflowRouter` with 10 mandatory rules + bounded inference |
| 3.5 Repeated identical failures bounded | VERIFIED WORKING | `failure_signature()`, `max_identical_failures` |
| 3.6 Approval for destructive/deployment | VERIFIED WORKING | `_approval_rule`, `requires_approval()` |
| 3.7 Deterministic rules exclude invalid | VERIFIED WORKING | All mandatory rules are pure functions |
| 3.8 Unit tests + CLI | VERIFIED WORKING | `tests/test_workflow.py`, `tests/test_router.py`, `cli.py` |
| 3.9 Log why each route chosen | VERIFIED WORKING | `RouteDecision.reason` + `RouteDecision.rules` |

**No repairs required.** This stage is solid.

---

### Stage 4 — Persistence and Context Reuse

| Task | Status | Evidence |
|------|--------|----------|
| 4.1 SQLite + migrations | VERIFIED WORKING | `store.py` with `STORE_SCHEMA_VERSION`, `_MIGRATIONS` |
| 4.2 Persist all task state | VERIFIED WORKING | `tasks`, `history`, `evidence`, `context_facts` tables |
| 4.3 Structured facts, not transcripts | VERIFIED WORKING | `add_fact()` with 5 kinds |
| 4.4 Distinguish fact types | VERIFIED WORKING | `ItemKind`: verified/requirement/hypothesis/question/execution |
| 4.5 Invalidate stale context | VERIFIED WORKING | `mark_stale()`, `stale` flag on facts |
| 4.6 No credentials stored | VERIFIED WORKING | Schema has no secret columns; test enforces this |
| 4.7 CLI inspect command | VERIFIED WORKING | `cli.py` with `inspect` subcommand |

**No repairs required.** This stage is solid.

---

### Stage 5 — OpenCode Integration

| Task | Status | Evidence |
|------|--------|----------|
| 5.1 Inspected OpenCode version + docs | VERIFIED WORKING | v2.0.26 confirmed; plugin API verified from docs |
| 5.2 Smallest supported integration | VERIFIED WORKING | Custom tools in `.opencode/tools/layasdlc.ts` |
| 5.3 Accept task → persistent record | VERIFIED WORKING | `opencode_bridge.py` `route` operation |
| 5.4 Compact structured task state | VERIFIED WORKING | `TaskState.as_prompt_state()` |
| 5.5 Next action + explanation | VERIFIED WORKING | Bridge returns `next_action`, `reason`, `rules` |
| 5.6 Controller can request all actions | VERIFIED WORKING | Router covers all 8 actions |
| 5.7 Replaceable coding adapter | VERIFIED WORKING | `CodingAdapter` protocol |
| 5.8 Supported OpenCode interfaces | VERIFIED WORKING | `@opencode-ai/plugin` `tool()` helper |
| 5.9 Least-privilege permissions | VERIFIED WORKING | `opencode.json`: route=ask, inspect=allow, approve=ask |
| 5.10 Log workflow transitions | VERIFIED WORKING | Event plugin + Python `get_logger` |
| 5.11 Safe cancel + progress inspection | VERIFIED WORKING | `inspect` tool + `deny_approval` |

**Gap:** No end-to-end test that actually starts OpenCode and exercises the plugin.
The TypeScript plugin exists but has no automated test that loads it in OpenCode.

**Required repairs:**
- [ ] Add an OpenCode plugin contract test (verifies the plugin file is syntactically valid and exports the expected tools)

---

### Stage 6 — Code-Aware Context Engineering

| Task | Status | Evidence |
|------|--------|----------|
| 6.1 Git diffs, filename, symbol, test-failure retrieval | VERIFIED WORKING | `from_git_diff`, `from_filename_search`, `from_symbol_search`, `from_test_failures` |
| 6.2 AST extraction where supported | PARTIALLY WORKING | Python `ast` module mentioned but **not implemented** — uses regex/line-based only |
| 6.3 Functions, classes, imports, call sites | PARTIALLY WORKING | Symbol search finds references but no AST-based extraction |
| 6.4 Deterministic ranking before model-based | VERIFIED WORKING | `rank_items()` with path overlap, Jaccard, kind priority |
| 6.5 Compact context package | VERIFIED WORKING | `ContextPackage` with objective, items, budget |
| 6.6 Configurable budget + reserved space | VERIFIED WORKING | `build_package()` with `budget_tokens`, `reserved_tokens` |
| 6.7 Deduplication | VERIFIED WORKING | `deduplicate()` with SHA-256 fingerprints |
| 6.8 Provenance for every fact | VERIFIED WORKING | `Source` on every `ContextItem` |
| 6.9 Never drop mandatory items | VERIFIED WORKING | Constraints/questions/security always included |
| 6.10 Token accounting | VERIFIED WORKING | `estimate_tokens()` + `measured` flag |

**Gap:** AST-based extraction for Python is mentioned in the module docstring but
not implemented. The current implementation uses regex/line-based search only.

**Required repairs:**
- [ ] Implement Python AST extraction for function/class definitions

---

### Stage 7 — Controlled Execution and Evidence Verification

| Task | Status | Evidence |
|------|--------|----------|
| 7.1 Bounded workflow | VERIFIED WORKING | `ExecutionEngine` with `max_cycles` |
| 7.2 Sandbox/isolation | VERIFIED WORKING | `sandbox` parameter, `_run_check` uses `cwd` |
| 7.3 Never overwrite user mods | VERIFIED WORKING | Engine only applies adapter-reported changes |
| 7.4 No arbitrary shell commands | VERIFIED WORKING | Adapter receives structured input, not shell |
| 7.5 Approval for destructive ops | VERIFIED WORKING | Router approval gate, `opencode.json` |
| 7.6 Treat repo files as untrusted | VERIFIED WORKING | Adapter output validated, test output captured |
| 7.7 Retry/time limits | VERIFIED WORKING | `max_cycles`, `max_retries`, `max_identical_failures`, `max_steps` |

**No repairs required.** This stage is solid.

---

### Stage 8 — Reproducible Evaluation

| Task | Status | Evidence |
|------|--------|----------|
| 8.1 Three configurations | VERIFIED WORKING | `BASELINE`, `OPTIMIZED`, `LAYASDLC` in `benchmark.py` |
| 8.2 Record all metrics | PARTIALLY WORKING | Metrics exist but **tokens are estimated, not measured** |
| 8.3 Separate measured from estimated | BROKEN | `measured_tokens` field exists but is **always False** in offline mode |
| 8.4 Fixed task set + repeats | VERIFIED WORKING | 8 tasks, `--repeat N` |
| 8.5 Document limitations | VERIFIED WORKING | Report includes Limitations section |
| 8.6 No unsupported causal claims | VERIFIED WORKING | "No causal claim" in report |
| 8.7 Reproducible benchmark script | PARTIALLY WORKING | Script exists but **no real-provider path** |

**Critical gaps:**
- [ ] No real-provider benchmark runner that collects actual usage metadata
- [ ] No `benchmarks/README.md` with methodology
- [ ] No version-controlled task manifest (tasks are hardcoded in `benchmark.py`)
- [ ] Token counts are always estimates — violates requirement 10.2
- [ ] No cost/latency calculation from provider pricing
- [ ] No confidence interval or variability measure

---

## Cross-Cutting Issues

### Documentation
| Issue | Severity |
|-------|----------|
| README says "Stage 2" — should say "Stage 8" | HIGH |
| README claims 139 tests — actual count is 542+ | HIGH |
| README lists OpenCode/SQLite as "not built" — both are built | HIGH |
| No `docs/setup.md` | HIGH |
| No `docs/verification-report.md` | MEDIUM |
| `.env.example` mentions `LAYA_ENGINE=sdk` but SDK cannot run here | MEDIUM |

### Testing
| Issue | Severity |
|-------|----------|
| No end-to-end smoke test exercising the full path | MEDIUM |
| No OpenCode plugin contract test | MEDIUM |
| No AST extraction test for Python | LOW |

### Benchmarking
| Issue | Severity |
|-------|----------|
| No real-provider benchmarking path | HIGH |
| Token counts are always estimates | HIGH |
| No cost calculation from provider pricing | MEDIUM |
| No variability/confidence interval | MEDIUM |

---

## Recommended Repair Order

1. **README.md** — rewrite to match reality (blocks contributor onboarding)
2. **`docs/setup.md`** — create complete setup guide (Stage 1 requirement)
3. **Real-provider benchmark** — add `benchmarks/` directory with real-provider runner
4. **Python AST extraction** — implement in `context.py`
5. **Verification report** — create `docs/verification-report.md`
6. **End-to-end smoke test** — add integration test for full path
7. **OpenCode plugin contract test** — verify plugin loads correctly

---

## Verification Commands

```bash
# Offline tests
cd services/decision
python -m pytest -m "not integration" -q

# Integration tests (requires network)
python -m pytest -m integration -q

# TypeScript build
cd ../../packages/contracts && npm run build

# Benchmark (offline, estimated tokens)
python -m layasdlc.benchmark run --repeat 1
```
