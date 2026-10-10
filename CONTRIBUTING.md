# Contributing to LayaSDLC

Thanks for helping. This project is small on purpose and unusually strict about
one thing: **never claim something is verified when it is only planned.**

---

## Ground rules

1. **Tick only what you have proven.** A checked box in [`TASKS.md`](TASKS.md) is
   a claim. Its "Done means" must be literally true, and the tests proving it
   must be green.
2. **Keep the offline suite green.**
   ```bash
   cd services/decision
   python -m pytest -m "not integration"
   ```
   It must pass with no network. If your change breaks it, the change is not
   ready.
3. **Separate verified from planned** in `README.md`. New capability ⇒ a row in
   *Verified capabilities* with evidence. New intention ⇒ a row in
   *Planned features*. Do not move an item across that line without evidence.
4. **Do not invent model output.** If Laya does not produce something (e.g. a
   rationale), the code must return `None`, not a plausible-sounding sentence.
5. **Do not widen tool permissions.** Model output must never grant access the
   policy withheld — layers 1 and 2 in `permissions.py` exist for this.

---

## Working a milestone (Stage 0)

The full rule set lives in [`Stages/stage0.md`](Stages/stage0.md). Two of its
rules govern how work is scheduled, so they apply to every contribution:

* **Work only on the explicitly requested milestone.** Do not start Stage 4
  because Stage 3 is nearly done; wait for the prompt.
* **Never implement the entire platform in one pass**, and never silently change
  the architecture or skip tests to make a milestone appear complete.

Every milestone runs this workflow, and a PR should make each step visible:

| Step | Action | Evidence in the PR |
|---|---|---|
| **A** | Inspect relevant files and documentation | links to what you read |
| **B** | State the implementation plan briefly | the PR description |
| **C** | Implement the smallest complete increment | a diff that does one thing |
| **D** | Run focused tests, type checks and linting | command output |
| **E** | Inspect the diff; confirm unrelated files were not changed | `git diff --stat` |
| **F** | Report changed files, commands, actual results, limitations, next milestone | the PR summary |

Two Stage 0 rules are especially easy to violate by accident:

* **If a required API or capability cannot be verified, stop that integration
  and explain the blocker.** Do not substitute a plausible-looking fake.
* **Never invent Laya APIs, capabilities, configuration options or model
  outputs.** If Laya cannot produce something (a rationale, a metric), return
  `null`/`None` and say so.

---

## Development setup

```bash
git clone https://github.com/<you>/LayaSDLC.git
cd LayaSDLC/services/decision
python -m venv .venv
.venv/bin/pip install pytest          # the only dev dependency
.venv/bin/python -m pytest -m "not integration"
```

The decision service has **zero runtime dependencies** — please keep it that way.
If you believe you need one, open an issue explaining why first.

### Integration tests (optional, needs network)

```bash
python -m pytest -m integration -s
# or against your own endpoint
LAYA_BASE_URL=https://your-host python -m pytest -m integration
```

> **Data caveat:** the default public endpoint reports
> `collecting_data: true`. Never point it at, or send through it, any secret,
> credential or private customer data.

---

## Making a change

```bash
git checkout -b <type>/<short-description>   # e.g. fix/single-option-503
# ... make the change, add or update tests ...
python -m pytest -m "not integration"
git add -A
git commit -m "<type>(<scope>): <what changed>"
git push -u origin HEAD
gh pr create --fill
```

### Commit types

| Prefix | Use for |
|---|---|
| `feat(scope)` | New capability that is tested |
| `fix(scope)` | Correcting behaviour that was wrong |
| `docs(scope)` | Documentation only |
| `test(scope)` | Tests only |
| `refactor(scope)` | No behaviour change |
| `chore(scope)` | Tooling, CI, housekeeping |

A commit should correspond to **one completed checklist item** where possible —
`TASKS.md` is the log of what actually happened.

---

## Pull requests

Use the PR template. A PR is reviewable when:

- [ ] Offline suite passes
- [ ] New behaviour has tests, including the failure path
- [ ] `TASKS.md` reflects the change
- [ ] Any new claim in `README.md` cites its evidence
- [ ] No secrets, tokens or `.env` files are included

### Review focus

Reviewers will specifically check: whether an `Outcome`/`source` value is honest,
whether the permission layers are still both enforced, and whether anything that
was previously `None` has been silently filled in with a plausible value.

---

## Reporting bugs

Use the **Bug report** issue template. Please include:

* the exact command and its output
* `Outcome`, `source`, `gate` and `error` from the `ControllerResult`
* whether the offline or the integration suite was running

Security issues go to [`SECURITY.md`](SECURITY.md) — **not** to a public issue.

---

## Code style

* Python: 100-column lines (`ruff` config lives in `pyproject.toml`), type hints
  on public functions, docstrings that explain *why* rather than *what*.
* Prefer a named exception over parsing a message; the error vocabulary in
  `errors.py` exists so callers can branch on cause.
* Comments that state a surprising fact must be checkable — cite the test or the
  ADR that proves them.

---

## Questions

Open an issue with the `question` label, or start a discussion. If you found a
place where the code and the documentation disagree, that is a bug — please file
it.
