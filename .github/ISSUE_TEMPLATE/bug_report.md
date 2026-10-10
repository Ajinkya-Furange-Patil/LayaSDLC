---
name: Bug report
about: Something behaves differently from what the docs claim
title: ""
labels: bug
assignees: ""
---

## Summary

<!-- One sentence -->

## Command and output

```text
$ python -m pytest ...
```

<!-- Paste the full failure, including the assertion diff -->

## Result details

| Field | Value |
|---|---|
| `outcome` | |
| `source` | (`engine` / `fallback` / `policy`) |
| `gate` | (`passed` / `abstained` / `unevaluated`) |
| `error` | |
| suite | offline (`-m "not integration"`) / integration |

## Expected

<!-- What the README or docs say should happen -->

## Environment

- OS:
- Python:
- Endpoint (`LAYA_BASE_URL`):
- Laya engine (`http` / `sdk`):

## Is this a docs bug too?

- [ ] The code is right and the docs are wrong
- [ ] The docs are right and the code is wrong
- [ ] Both are wrong
