# LayaSDLC — Task Checklist

> **This file is the operational backlog.** It is meant to be run, not admired:
> each item states its own acceptance criteria, and an item is only ticked when
> those criteria are met *and* the test suite is green. Every completed item
> lands on `main` as its own commit before work moves on.

---

## How to operate this checklist

```bash
# 1. pick the next unticked item under the current milestone
# 2. do the work
# 3. prove it
cd services/decision
python -m pytest -m "not integration"     # fast, offline, must stay green
python -m pytest -m integration           # real Laya endpoint, opt-in
# 4. record it here, then commit and push
git add -A && git commit -m "<type>(<scope>): <what changed> — closes #<item>"
git push
```

**Rules for ticking a box**

| Rule | Why |
|---|---|
| The stated "Done means" is literally true | A box is a claim, not a hope |
| Offline suite passes (`-m "not integration"`) | Regressions must be caught without network |
| Nothing was invented (see *Verified vs planned* in the README) | The whole point of this project |
| The change is committed and pushed | GitHub is the source of truth |

**Status legend:** `[x]` done and pushed · `[~]` in progress · `[ ]` not started

---

## Milestone 1 — Environment & reconnaissance — **[x] DONE**

- [x] **1.1** Record host capability (OS, Node, Python, Git, Docker, OpenCode, tsc)
      — *Done means:* `docs/adr/0001-*` states the measured numbers.
- [x] **1.2** Decide local vs cloud Laya after measuring, not assuming
      — *Done means:* RAM/headroom and Python-version constraints are written down
      with figures, and the verdict follows from them.
- [x] **1.3** Verify the live endpoint instead of trusting the docs
      — *Done means:* a real `POST /v1/systemone` returned HTTP 200 with
      `answers` + `usage`, and the error shapes (400/422/5xx/DNS) are recorded.
- [x] **1.4** Read the real `laya` package APIs before coding against them
      — *Done means:* `laya.load(...)`, `Agent.system_one(...)` and the question
      types were read from downloaded source, not guessed.

## Milestone 2 — Decision-service foundation (Stage 1) — **[x] DONE**

- [x] **2.1** Typed contracts + versioned `DecisionEnvelope` (`SCHEMA_VERSION`)
- [x] **2.2** Typed error vocabulary (rejections ≠ transport failures)
- [x] **2.3** Workflow controller: timeout → validate → gate → fallback → metrics
- [x] **2.4** Deterministic safety classification + approval gate (never a model output)
- [x] **2.5** Logging + metrics with latency and usage recording
- [x] **2.6** Health check reporting engine, fallback, permissions and capabilities
- [x] **2.7** Zero runtime dependencies (`stdlib` only; `pytest` is the only dev dep)
      — *Done means:* `dependencies = []` in `pyproject.toml` and the suite runs.

## Milestone 3 — Replaceable decision engine (Stage 2) — **[x] DONE**

- [x] **3.1** `DecisionEngine` protocol + `FakeEngine` for unit tests
- [x] **3.2** Four bounded decision types, each with a closed canonical option set
- [x] **3.3** Validation rejects malformed / unsupported / out-of-scope answers
- [x] **3.4** Confidence gate with a deterministic fallback under the same threshold
- [x] **3.5** Tool permissions enforced **twice** — before and after any engine call
- [x] **3.6** `LayaHttpEngine` speaking the verified `POST /v1/systemone` wire protocol
- [x] **3.7** `LayaSdkEngine` seam for the local `laya` package (unavailable on this host)
- [x] **3.8** Integration tests that use **real** Laya and never fake a success
- [x] **3.9** Real-endpoint findings fed back into the code:
      - [x] 503 `please retry` was raised *outside* the retry loop → moved inside
      - [x] single-option questions always 503 → settled from policy, not padded
      - [x] watchdog and transport timeouts raced → watchdog now a backstop only

## Milestone 4 — GitHub publication & community — **[~] IN PROGRESS**

- [x] **4.1** `git init`, identity configured, `.gitignore` written
- [x] **4.2** Test suite green: **139 offline + 7 integration**
- [ ] **4.3** `README.md` separating **verified capabilities** from **planned features**
- [ ] **4.4** `TASKS.md` (this file) committed as the live checklist
- [ ] **4.5** `docs/architecture.md` — the boundaries and what must not mix
- [ ] **4.6** `docs/adr/0001-environment-capability.md`
- [ ] **4.7** `docs/adr/0002-laya-inference-path.md`
- [ ] **4.8** `.env.example` with **no secrets**
- [ ] **4.9** `LICENSE` (Apache-2.0), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`
- [ ] **4.10** Issue templates + pull-request template
- [ ] **4.11** Create the public GitHub repository and push `main`
      — *Done means:* `gh repo view` resolves and the README renders on GitHub.

## Milestone 5 — OpenCode boundary (TypeScript) — **[ ] TODO**

- [ ] **5.1** `packages/` TypeScript package with `package.json` + `tsconfig.json`
- [ ] **5.2** `DecisionEnvelope` type mirrored from `contracts.py` (structurally identical)
- [ ] **5.3** Compiles cleanly under `tsc --noEmit` with no runtime deps
- [ ] **5.4** Contract-parity check so Python and TypeScript cannot drift apart
      — *Done means:* a test asserts both sides describe the same field names.

## Milestone 6 — Documentation completeness — **[ ] TODO**

- [ ] **6.1** `docs/setup.md` — reproduce the environment from a clean machine
- [ ] **6.2** `docs/decisions.md` — why each Stage 2 rule exists
- [ ] **6.3** `CHANGELOG.md` seeded from the milestone commits

## Milestone 7 — Stage 3+ (explicitly out of scope until scheduled)

- [ ] **7.1** OpenCode event integration *(Stage 2 exclusion)*
- [ ] **7.2** Autonomous code execution *(Stage 2 exclusion)*
- [ ] **7.3** SQLite persistence *(Stage 1 exclusion)*
- [ ] **7.4** Local `laya` inference — blocked: 7.6 GB RAM host, needs ~1.3 GB per
      checkpoint + torch, and `laya-decision-api` requires Python `<3.14`
- [ ] **7.5** Frontend / dashboard
- [ ] **7.6** Multi-agent orchestration

---

## Known constraints (do not "fix" by accident)

- **Endpoint caveat:** `https://laya.inference.zaitlabs.com/health` reports
  `collecting_data: true`. Do not send secrets, credentials or private data
  through it.
- **The local SDK engine cannot be validated on this host.** It ships behind
  `laya_sdk_available()` and skips rather than pretending to work.
- **Confidence is `max(probabilities)`**, not Laya's entropy `confidence` field.
- **Safety is keyword matching, never a model output.**
