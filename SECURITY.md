# Security policy

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report them privately via GitHub's
[**Report a vulnerability**](../../security/advisories/new) button on this
repository, or email the maintainer through the address on their GitHub profile.

Include:

* what you did and what happened
* the affected file and, if possible, a minimal reproduction
* the impact you believe it has
* whether you have disclosed this anywhere else already

You should receive an acknowledgement within a few days. Please allow a
reasonable window for a fix before any public disclosure.

---

## Scope

In scope:

* anything that lets model output **widen tool permissions** beyond what
  `ToolPermissionPolicy` permits (layers 1 and 2 in `permissions.py`)
* anything that lets a **malformed, unsupported or out-of-scope** model answer
  reach a caller as though it were valid
* a **safety-classification bypass** — destructive or deployment work that
  reaches `Action.PROCEED` without approval
* secrets, tokens or private data committed to this repository
* dependency or supply-chain issues

Out of scope:

* issues in the **third-party public Laya endpoint** itself — report those
  upstream; we only consume it
* a low-confidence decision being *wrong* — that is the point of the confidence
  gate and the fallback, not a security defect
* denial of service against the public free endpoint by running the integration
  suite in a tight loop

---

## Data handling — read this before using the default endpoint

The default `LAYA_BASE_URL` is a **public, keyless** endpoint whose
`/health` reports:

```json
{ "collecting_data": true }
```

Treat every request you send to it as **public**:

* **No** API keys, tokens, passwords or connection strings
* **No** private customer data, unreleased source code, or personal data
* **No** internal hostnames or infrastructure details

If you need to send that kind of material, run Laya against your own endpoint
and set `LAYA_BASE_URL` accordingly.

---

## Configuration safety

* `.env` is git-ignored; `.env.example` is committed and must stay
  placeholder-only.
* Never commit `.env`, `.env.local`, key files or model weights.
  `.gitignore` already excludes `.env*` (except the example), `*.safetensors`,
  `*.onnx` and `.laya-cache/`.
* The service has **no runtime dependencies**, which keeps the supply-chain
  surface deliberately small. Please raise an issue before adding one.

---

## Supported versions

| Version | Supported |
|---|---|
| `main` | ✅ actively developed |
| older commits | ❌ no backports during Stage 1–2 |
