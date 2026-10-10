# LayaSDLC — Task Checklist

> **Authoritative plan:** [`Stages/`](Stages/) — `stage0.md` … `stage8.md`.
> This file tracks *execution* against that plan. Where they disagree, `Stages/`
> wins and this file is wrong.
>
> An item is only ticked when its acceptance criteria are literally true **and**
> the test suite is green. Every completed milestone is committed and pushed
> before the next one starts.

---

## Operating contract (Stage 0 — always in force)

Stage 0 is not a one-shot milestone; it is how every milestone below is run.

**Mandatory engineering rules** (full text in [`Stages/stage0.md`](Stages/stage0.md)):

1. Never implement the entire platform in one pass.
2. **Work only on the explicitly requested milestone.**
3. Inspect the existing codebase before changing anything.
4. Read official docs and actual installed package interfaces before using an API.
5. Never invent Laya APIs, capabilities, configuration options or model outputs.
6. Separate decision-making, execution, evidence and permissions.
7. Keep model-specific logic behind replaceable adapters.
8. Use deterministic rules as a fallback when model decisions fail or are uncertain.
9. Do not treat confidence as proof of correctness.
10. Never declare a fix successful without appropriate verification.
11. Track actual token usage when available; mark unavailable metrics unknown, never fabricate.
12. Minimize dependencies, duplicated logic, generated files and unnecessary abstractions.
13. Never overwrite existing user work or expose secrets.
14. Require explicit authorization for destructive actions, publishing, deployment and high-impact operations.
15. Do not silently change the architecture or skip tests to make a milestone appear complete.

**Required workflow for every milestone:**

| Step | Action |
|---|---|
| **A** | Inspect relevant files and documentation |
| **B** | State the implementation plan briefly |
| **C** | Implement the smallest complete increment |
| **D** | Run focused tests, type checks and linting where configured |
| **E** | Inspect the diff; verify unrelated files were not changed |
| **F** | Report changed files, commands executed, actual results, limitations, next milestone |

> **"If a required API or capability cannot be verified, stop that integration
> and explain the blocker. Do not replace it with a fabricated implementation."**
>
> **"Wait for the explicit milestone prompt before beginning development."**

---

## Stage status

| Stage | Title | Status |
|---|---|---|
| **0** | Principal-engineer rules and workflow | 🟡 standing — in force for all |
| **1** | Repository reconnaissance and project foundation | ✅ done |
| **2** | Real, replaceable decision-engine adapter | ✅ done |
| **3** | Workflow router (state machine + CLI demo) | ⬜ **next — awaiting prompt** |
| **4** | Persistent engineering state and context reuse | ⬜ |
| **5** | Connect LayaSDLC to OpenCode | ⬜ |
| **6** | Code-aware context engineering | ⬜ |
| **7** | Controlled execution and evidence-based verification | ⬜ |
| **8** | Reproducible evaluation of LayaSDLC | ⬜ |

### Exclusions that are **temporary**, not permanent

Stage 1/2 exclusions are lifted by later stages rather than being permanent
project limits. Do not cite them as reasons to avoid later work.

| Excluded in | Lifted by |
|---|---|
| Database persistence (Stage 1) | **Stage 4** — SQLite, migrations, resume across restarts |
| OpenCode event integration (Stage 2) | **Stage 5** — plugin/tool integration |
| Autonomous code execution (Stage 2) | **Stage 7** — controlled execution with evidence |
| Frontend | Stage 8 allows a *small* dashboard/CLI report |
| Multi-agent orchestration | not scheduled in Stage 0–8 |
| Local `laya` inference | blocked by hardware — see ADR-0001 |

---

## Stage 1 — Repository reconnaissance and project foundation ✅

- [x] **1.1** Report OS/runtimes, OpenCode install + config, Laya package/weights/runtime status
      — *Done means:* [`docs/adr/0001-environment-capability.md`](docs/adr/0001-environment-capability.md) carries the measured numbers.
- [x] **1.2** Determine whether Laya runs locally and what it requires
      — *Done means:* verdict follows from measured RAM/Python constraints, not assumption.
- [x] **1.3** Verify official Laya installation and inference methods for the installed version
      — *Done means:* APIs read from downloaded package source, not guessed.
- [x] **1.4** Minimum architecture with the five separations (engine interface, service adapter, controller, task/evidence models, logging/metrics)
- [x] **1.5** README, architecture decisions, `.env.example` without secrets
- [x] **1.6** Typed task and decision contracts that import/compile
- [x] **1.7** Health check for the decision service
- [x] **1.8** Unit-test configuration, `.gitignore`, dependency manifests
- [x] **1.9** README separates **verified capabilities** from **planned features**

**Acceptance:** original files intact ✅ · setup matches environment ✅ · contracts importable ✅ · basic tests pass ✅ · engine swappable without rewriting controller ✅ · README verified/planned split ✅

## Stage 2 — Real, replaceable decision-engine adapter ✅

- [x] **2.1** Versioned decision schema (`decision_id`, `task_id`, `decision_type`, `allowed_options`, `selected_option`, `confidence`, `rationale`, model id/version, latency, usage)
- [x] **2.2** Four bounded decisions: task classification, workflow selection, retry-vs-escalate, context priority
- [x] **2.3** Validate every returned decision against schema and allowed options
- [x] **2.4** Reject malformed / unsupported / out-of-scope outputs
- [x] **2.5** Configurable timeouts and deterministic fallback
- [x] **2.6** Model output can never bypass tool permissions (enforced twice)
- [x] **2.7** Inference replaceable through a common interface
- [x] **2.8** Fake engine for unit tests; separate integration test for real Laya
- [x] **2.9** Real-endpoint findings fed back into the code:
      - [x] 503 `"please retry"` was raised outside the retry loop → moved inside
      - [x] single-option questions always 503 → settled from policy, never padded
      - [x] watchdog/transport timeouts raced → watchdog is a backstop only

**Acceptance:** ≥1 real bounded decision works through Laya ✅ (7 integration tests) · invalid decisions rejected safely ✅ · fallback tested ✅ · no paid inference ✅ · latency + usage recorded ✅

## Stage 3 — Workflow router ⬜ (next; awaiting explicit prompt)

- [ ] **3.1** Eight workflow actions: `INSPECT_REPOSITORY`, `RETRIEVE_CONTEXT`, `IMPLEMENT_CHANGE`, `RUN_TESTS`, `REVIEW_DIFF`, `ESCALATE`, `REQUEST_APPROVAL`, `COMPLETE`
- [ ] **3.2** Task state machine: current state, allowed next states, action history, completion conditions
- [ ] **3.3** Transition validator that rejects impossible transitions
      — *Done means:* a task cannot become `COMPLETE` merely because Laya selected it.
- [ ] **3.4** Routing policy: simple deterministic tasks skip LLM calls; source changes retrieve context first; high-risk/ambiguous → inspect or escalate; failed tests → diagnose / bounded retry / escalate
- [ ] **3.5** Repeated identical failures do not trigger infinite retries
- [ ] **3.6** Deployment and destructive actions require approval
- [ ] **3.7** Deterministic rules exclude invalid transitions and enforce mandatory checks
- [ ] **3.8** Unit tests + CLI demonstration on **mock** tasks
- [ ] **3.9** Log *why* each route was chosen and which rules constrained it

**Acceptance:** demonstrate ≥5 scenarios — simple task, bug fix, failed test, ambiguous task, high-risk action · no real repository modifications executed.

## Stage 4 — Persistent engineering state and context reuse ⬜

- [ ] **4.1** SQLite persistence (or a justified alternative), with migrations
- [ ] **4.2** Persist task id/objective, workflow state, repo revision + working-tree status, decisions, completed steps, open questions, evidence refs, model calls/latency/usage, retry and failure history
- [ ] **4.3** Store concise structured engineering facts, not conversation transcripts
- [ ] **4.4** Distinguish verified facts / user requirements / model hypotheses / unresolved questions / execution results
- [ ] **4.5** Invalidate stale context when relevant inputs change; stale evidence is not current
- [ ] **4.6** Store no credentials or unnecessary sensitive data
- [ ] **4.7** CLI command to inspect task state and its evidence

**Acceptance:** task survives restart · resumes from last valid state · repeated requests do not duplicate completed steps · migrations and persistence tests pass.

## Stage 5 — Connect LayaSDLC to OpenCode ⬜

- [ ] **5.1** **Before coding:** inspect installed OpenCode version + official docs; verify plugin hooks, tool interfaces, permissions, model invocation
- [ ] **5.2** Smallest supported integration (custom tool or plugin)
- [ ] **5.3** Accept a task → create persistent task record
- [ ] **5.4** Send compact structured task state to the controller
- [ ] **5.5** Return next permitted action + concise explanation
- [ ] **5.6** Controller can request inspection, context retrieval, implementation, tests or escalation
- [ ] **5.7** Coding-model invocation behind a replaceable adapter
- [ ] **5.8** Use supported OpenCode interfaces — no scraping terminal output, no undocumented internals
- [ ] **5.9** Least-privilege tool permissions; confirmation before repository-changing operations
- [ ] **5.10** Log workflow transitions and actual model usage
- [ ] **5.11** Safe cancel + progress inspection

**Acceptance:** one end-to-end workflow initiated from OpenCode (mock coding adapter allowed): creates a task, obtains a decision, returns a valid action, records the result, displays current state.

## Stage 6 — Code-aware context engineering ⬜

- [ ] **6.1** Start with git diffs, filename search, symbol search, test-failure retrieval
- [ ] **6.2** AST extraction only where a suitable parser exists
- [ ] **6.3** Identify relevant functions, classes, imports, call sites, direct dependencies
- [ ] **6.4** Deterministic relevance ranking *before* any model-based ranking
- [ ] **6.5** Compact context package: objective, snippets, paths + line ranges, dependencies, test results, constraints, open questions
- [ ] **6.6** Configurable context budget with reserved space for the response
- [ ] **6.7** Deduplicate snippets; never resend unchanged summaries
- [ ] **6.8** Provenance for every fact (file, revision or test result)
- [ ] **6.9** Never silently drop mandatory requirements or security-critical evidence to meet a budget
- [ ] **6.10** Token accounting: measure with the target tokenizer when available, otherwise label estimates clearly

**Acceptance:** targeted retrieval reduces input size on suitable tasks while preserving needed context; tests cover stale git revisions, missing files, large files and budget exhaustion; full-file vs targeted comparison reported. No embeddings/vector DB unless the benchmark demands it.

## Stage 7 — Controlled execution and evidence-based verification ⬜

- [ ] **7.1** Workflow: inspect → retrieve context → select workflow → invoke coding adapter → inspect diff → run tests/linters/type checks → record evidence → accept only if checks pass → else diagnose/retry/escalate
- [ ] **7.2** Isolated working tree or sandbox where practical
- [ ] **7.3** Never overwrite unrelated user modifications
- [ ] **7.4** No arbitrary model-generated shell commands without policy checks
- [ ] **7.5** Approval required for destructive ops, secrets, publishing, deployment
- [ ] **7.6** Treat repository files, tool output and model responses as untrusted input
- [ ] **7.7** Retry/time limits; stop when the same failure repeats without new evidence

**Acceptance:** demonstrate a passing change, a deliberately failing test, a malformed model response, an exhausted retry budget, and a task requiring human approval — every outcome recorded in persistent history.

## Stage 8 — Reproducible evaluation ⬜

- [ ] **8.1** Three configurations: baseline / optimized baseline (deterministic routing + compact context + persistent state) / LayaSDLC (+ Laya decisions) — same coding model, task set, repo snapshots, verification criteria
- [ ] **8.2** Record input/output tokens, decision-model cost, coding-model tokens/cost, total cost, wall-clock latency, verified completion rate, test pass rate, routing accuracy, model calls, retries, fallback and escalation rates
- [ ] **8.3** Separate measured values from estimates; include failed and incomplete runs
- [ ] **8.4** Fixed task set, baseline per task, comparable runs, repeats for variability, aggregate + per-task reporting
- [ ] **8.5** Document limitations, failures, confounding factors
- [ ] **8.6** No causal claim the experiment does not support
- [ ] **8.7** Reproducible benchmark script, machine-readable results, comparison report, small dashboard/CLI report

**Acceptance:** results reproducible from documented instructions — *the project is complete only then.*

---

## How to operate a milestone

```bash
# C/D — implement, then prove it
cd services/decision
python -m pytest -m "not integration"     # offline, must always be green
python -m pytest -m integration           # real Laya, opt-in
cd ../../packages/contracts && npm run build   # tsc, when contracts changed

# E — inspect the diff, confirm scope
git status --short && git diff --stat

# F — commit, push, report
git add -A && git commit -F <message-file> && git push
```

**Never tick a box you have not proven.** See `CONTRIBUTING.md`.

---

## Known constraints (do not "fix" by accident)

- **Public endpoint caveat:** the default `LAYA_BASE_URL` reports
  `collecting_data: true`. Never send secrets or private data through it.
- **Local `laya` cannot run here:** 7.6 GB RAM / 1.9 GB free vs ~1.3 GB per
  checkpoint + torch, and `laya-decision-api` needs Python `<3.14` (host: 3.14.3).
  `LayaSdkEngine` skips rather than pretending. See ADR-0001.
- **Confidence is `max(probabilities)`**, not Laya's entropy `confidence` field.
- **Safety classification is keyword matching, never a model output.**
- **Laya generates no text** ⇒ `rationale` is always `None` from a Laya engine.
