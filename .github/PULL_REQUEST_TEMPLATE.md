## What changed

<!-- One sentence. Which checklist item does this close? e.g. closes TASKS 4.3 -->

Closes TASKS #

## Why

<!-- The problem, not the feature. If this is a "verified capability" claim, say
     exactly what proves it (test name, measurement, endpoint response). -->

## How it was proven

- [ ] Offline suite passes: `python -m pytest -m "not integration"`
- [ ] Integration suite passes or skips honestly: `python -m pytest -m integration`
- [ ] New behaviour has tests, **including the failure path**
- [ ] `TASKS.md` updated with this item ticked
- [ ] Any new claim in `README.md` sits in the right section (verified vs planned)

## Checklist

- [ ] No runtime dependencies added (or an issue explains why one is unavoidable)
- [ ] Model output still cannot widen tool permissions (layers 1 **and** 2 intact)
- [ ] Nothing that was `None` has been filled in with a plausible-looking value
- [ ] No secrets, tokens, `.env` files or model weights included
- [ ] Docs/ADRs updated where behaviour or rationale changed

## Notes for reviewers

<!-- Anything subtle. If you faked nothing, say so: integration tests must never
     simulate a successful real inference. -->
