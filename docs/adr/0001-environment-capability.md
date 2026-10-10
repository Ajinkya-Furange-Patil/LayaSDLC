# ADR-0001: Environment capability — measure before installing

- **Status:** Accepted
- **Date:** 2026-10-10
- **Decides:** whether Laya can run locally on this host, and what to do instead

## Context

The project needs the Laya decision model for real inference. Before writing a
line of integration code, the host was inspected rather than assumed.

### Measured

| Fact | Value |
|---|---|
| OS | Windows 11 (build 26300) |
| CPU/GPU | NVIDIA GTX 1650, 4 GB VRAM |
| RAM | **7.6 GB total, ~1.9 GB free** at inspection time |
| Python | **3.14.3** |
| Node / npm | v24.14.0 / 11.12.1 |
| Git | 2.53.0 |
| Docker | 29.4.2 (daemon **not** running) |
| OpenCode | v2.0.26 on `PATH` |
| `tsc` | 6.0.3 (global) |
| `torch` | 2.11.0+cu126 — already installed, CUDA verified working |
| `transformers` | 5.8.0 — already installed |
| `laya` package | **not installed** |
| Laya weights | **none** (HF cache holds only `bert-base-uncased` and `GLM-5.1`) |
| OpenCode config | none anywhere (no global `opencode.json(c)`, no project config) |

## Decision

**Do not install Laya locally. Use a remote Laya HTTP endpoint as the primary
path, and keep a local-SDK engine as an optional seam that skips when the
package is absent.**

## Why

1. **Memory.** ~1.3 GB *per resident checkpoint* plus a torch runtime, against
   1.9 GB free. That is not headroom; it is a swap storm waiting to happen,
   and this project values a machine that stays usable while it runs.
2. **Python version.** `laya-decision-api` declares
   `Requires-Python: >=3.11,<3.14`. The host runs 3.14.3, so that package
   cannot be installed here without a second interpreter and a second venv
   — an entire toolchain to maintain for one dependency.
3. **The wire protocol is the same either way.** The remote endpoint speaks
   `POST /v1/systemone`, which is what the local SDK exposes too, so choosing
   remote does not bake remote into the design.

## Consequences

* `LayaHttpEngine` is the primary engine; its request/response shapes were
  captured from a real endpoint **before** the module was written.
* `LayaSdkEngine` exists but reports unavailable on this host. It skips rather
  than faking — see `laya_sdk_available()`.
* **Data-handling caveat:** the default endpoint's `/health` reports
  `collecting_data: true`. It must never receive secrets or private data. This
  is recorded in `README.md` and `SECURITY.md`, not just here.
* Local inference (Milestone 7.4) stays blocked until the host changes. It is
  listed as a constraint in `TASKS.md` so nobody "fixes" it by silently
  installing 1.3 GB of weights.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Install local Laya | Out of RAM; Python constraint blocks `laya-decision-api` |
| Downgrade Python to 3.12 | A second interpreter toolchain for one dependency; the memory problem remains regardless |
| Docker | Daemon not running, and a container does not create RAM |
| Skip real inference, simulate it | Defeats the purpose; Stage 2 forbids simulating a successful real inference |
