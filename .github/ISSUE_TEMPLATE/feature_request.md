---
name: Feature request
about: Propose something that does not exist yet
title: ""
labels: enhancement
assignees: ""
---

## What

<!-- One sentence -->

## Problem it solves

<!-- What can you not do today? -->

## Where it would live

<!-- Which boundary owns it? See docs/architecture.md — engine, validation,
     permissions, controller, metrics, or safety. If you are not sure, say so. -->

- [ ] `engine` / `engines/` — how an answer is obtained
- [ ] `validation` — whether an answer is well-formed and in scope
- [ ] `permissions` — what tools a decision may name
- [ ] `controller` — sequencing one decision
- [ ] `metrics` / `health` — recording what happened
- [ ] `safety` — destructive/deployment classification
- [ ] TypeScript boundary (`packages/`)
- [ ] documentation / tooling

## Stage impact

- [ ] Adds no runtime dependency
- [ ] Does not require persistence (Stage 1 excludes it)
- [ ] Does not require autonomous execution (Stage 2 excludes it)
- [ ] Does not widen tool permissions granted to model output

## How would we prove it works?

<!-- Describe the test. "It looks right" is not an acceptance criterion. -->
