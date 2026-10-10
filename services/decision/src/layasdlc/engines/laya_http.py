"""Real Laya over HTTP -- the Jev-compatible ``POST /v1/systemone`` wire protocol.

Why this is the primary inference path (ADR-0002)
-------------------------------------------------
The host has 7.6 GB RAM with ~1.9 GB free at inspection time, against a model
that needs ~1.3 GB *per resident checkpoint* plus a torch runtime, and
``laya-decision-api`` declares ``Requires-Python: >=3.11,<3.14`` while the host
runs 3.14.3. A remote endpoint gives real Laya inference without competing for
that memory, and the wire protocol is identical to what the local SDK speaks.

The request/response shapes below were captured live from a real endpoint
before this module was written -- they are not guessed::

    POST /v1/systemone
    {"state": <str|obj>, "questions": {"selection": {...}}, "model": "<optional>"}

    200 {"model":"laya-0.3.4/typed-decisions",
         "answers":{"selection":{"type":"choice","choice":"...","confidence":0.3026,
                                 "probabilities":{...}}},
         "usage":{"input_tokens":213,"output_tokens":0}}
    400 {"detail":[{"loc":[...],"msg":"...","type":"unknown_model"}]}
    422 {"detail":[{"loc":[...],"msg":"...","type":"value_error"}]}
    401/403 credentials refused   429 rate limited   5xx unavailable
    connection/DNS failure        -> EngineUnavailable   timeout -> EngineTimeout

Accepted ``model`` values are ``laya``, ``laya/{english,multilingual,
typed-decisions}`` and ``typesafe/jev``. ``laya-english`` is **not** accepted --
it returns HTTP 400 ``unknown_model``, which was verified directly.

``rationale`` is always ``None``: Laya never generates text, so writing a
sentence here would be inventing data the model did not produce.
"""

from __future__ import annotations

import json
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from ..contracts import Usage
from ..engine import EngineAnswer, EngineRequest, answer_confidence, ranked_probabilities
from ..errors import (
    EngineAuthError,
    EngineRateLimited,
    EngineRejected,
    EngineTimeout,
    EngineUnavailable,
    MalformedResponse,
)
from ..questions import question_for

_VERSION_RE = re.compile(r"laya[-/](\d+\.\d+\.\d+)")


@dataclass(frozen=True)
class RawResponse:
    """The minimum an HTTP transport must report back."""

    status: int
    body: bytes


class Transport:
    """Injectable HTTP seam so unit tests never open a socket."""

    def post(self, url: str, *, body: bytes, headers: Mapping[str, str],
             timeout_s: float) -> RawResponse:
        raise NotImplementedError


class UrllibTransport(Transport):
    """Default transport: stdlib ``urllib`` only.

    Does not raise on HTTP error status -- it returns the status so the engine
    owns the error taxonomy in exactly one place. Network-level failures still
    raise and are translated by the caller.
    """

    def post(self, url: str, *, body: bytes, headers: Mapping[str, str],
             timeout_s: float) -> RawResponse:
        request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
                return RawResponse(status=response.getcode(), body=response.read())
        except urllib.error.HTTPError as exc:
            payload = exc.read() if hasattr(exc, "read") else b""
            return RawResponse(status=exc.code, body=payload or b"")
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                raise EngineTimeout(f"request to {url} timed out after {timeout_s}s") from exc
            raise EngineUnavailable(f"cannot reach {url}: {reason}") from exc
        except (socket.timeout, TimeoutError) as exc:
            raise EngineTimeout(f"request to {url} timed out after {timeout_s}s") from exc


@dataclass
class LayaHttpEngine:
    """Talks to a real Laya endpoint over ``POST /v1/systemone``."""

    base_url: str
    name: str = "laya-http"
    version: Optional[str] = None          # discovered from the response's model field
    api_key: Optional[str] = None
    model: Optional[str] = None
    #: Transient 5xx/429 are common on the free shared endpoint, so one blind
    #: retry is not enough; permanent refusals are still never retried.
    max_attempts: int = 3
    backoff_s: float = 0.25
    transport: Transport = field(default_factory=UrllibTransport)
    sleep: Any = time.sleep                # injectable so tests never actually wait

    def __post_init__(self) -> None:
        self.base_url = (self.base_url or "").rstrip("/")

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/v1/systemone"

    def available(self) -> bool:
        """Configuration probe only -- no network, no model load.

        A health check that opens a socket (or downloads weights) is not a health
        check; use :meth:`probe` when a real readiness check is wanted.
        """
        return bool(self.base_url)

    def probe(self, timeout_s: float = 5.0) -> dict[str, Any]:
        """Optional live readiness check against ``GET /health``."""
        request = urllib.request.Request(f"{self.base_url}/health", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
                document = json.loads(response.read().decode("utf-8", errors="replace"))
            return {"reachable": True, "detail": document}
        except Exception as exc:  # noqa: BLE001 - a failed probe is a reportable finding
            return {"reachable": False, "detail": f"{type(exc).__name__}: {exc}"}

    def decide(self, request: EngineRequest) -> EngineAnswer:
        questions = question_for(request.decision_type, request.allowed_options)
        payload: dict[str, Any] = {"state": dict(request.state), "questions": questions}
        if request.model or self.model:
            payload["model"] = request.model or self.model

        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        attempts = max(1, self.max_attempts)
        per_attempt_s = self._attempt_budget(request.timeout_s, attempts)

        last_error: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                raw = self.transport.post(
                    self.endpoint, body=body, headers=headers, timeout_s=per_attempt_s
                )
                latency_ms = (time.perf_counter() - started) * 1000.0
                # Interpretation must sit *inside* the retry loop. A 503 arrives
                # here as EngineUnavailable and its body literally reads "the
                # model is temporarily unavailable, please retry" -- raised from
                # outside the loop, as it was before, that instruction was never
                # acted on and a transient blip became a hard failure.
                return self._interpret(raw, latency_ms, request=request)
            except (EngineTimeout, EngineUnavailable, EngineRateLimited) as exc:
                last_error = exc
                if attempt < attempts and exc.retryable:
                    self.sleep(self.backoff_s * (2 ** (attempt - 1)))
                    continue
                # EngineRejected/EngineAuthError/MalformedResponse are siblings,
                # not subclasses, of these -- permanent refusals are never
                # retried.
                raise

        assert last_error is not None
        raise last_error

    #: Smallest per-attempt slice, so a tiny total timeout still makes one real try.
    MIN_ATTEMPT_TIMEOUT_S = 1.0

    def _attempt_budget(self, total_timeout_s: float, attempts: int) -> float:
        """Slice the caller's *total* budget across attempts.

        ``EngineRequest.timeout_s`` is the budget for obtaining an answer, and
        the controller's watchdog enforces exactly that wall-clock figure.
        Handing every retry the full value would let this engine overrun it by a
        factor of ``attempts``, so the planned backoff is subtracted first and
        the remainder is divided evenly.
        """
        backoff_total = sum(self.backoff_s * (2 ** i) for i in range(attempts - 1))
        remaining = total_timeout_s - backoff_total
        return max(self.MIN_ATTEMPT_TIMEOUT_S, remaining / attempts)

    # --- response interpretation: the single place the taxonomy lives --------------------

    def _interpret(self, raw: RawResponse, latency_ms: float, *,
                   request: EngineRequest) -> EngineAnswer:
        text = raw.body.decode("utf-8", errors="replace") if raw.body else ""

        if raw.status in (401, 403):
            raise EngineAuthError(
                f"endpoint refused credentials (HTTP {raw.status}): {_detail(text)}",
                http_status=raw.status,
            )
        if raw.status == 429:
            raise EngineRateLimited(f"rate limited (HTTP 429): {_detail(text)}")
        if raw.status in (400, 422):
            raise EngineRejected(
                f"endpoint rejected the request (HTTP {raw.status}): {_detail(text)}",
                http_status=raw.status,
                detail=_detail_list(text),
            )
        if raw.status >= 500:
            raise EngineUnavailable(f"endpoint failed (HTTP {raw.status}): {_detail(text)}")
        if raw.status != 200:
            raise EngineUnavailable(f"unexpected HTTP {raw.status}: {_detail(text)}")

        try:
            document = json.loads(text) if text else None
        except json.JSONDecodeError as exc:
            raise MalformedResponse(f"response body is not JSON ({exc})", raw=text[:2000]) from exc
        if not isinstance(document, dict):
            raise MalformedResponse(
                f"expected a JSON object, got {type(document).__name__}", raw=text[:2000]
            )

        answers = document.get("answers")
        if not isinstance(answers, dict):
            raise MalformedResponse("response has no 'answers' object", raw=text[:2000])

        selection = answers.get("selection")
        if not isinstance(selection, dict):
            raise MalformedResponse(
                "response has no 'answers.selection' object", raw=text[:2000]
            )

        option = selection.get("choice")
        if not isinstance(option, str) or not option.strip():
            # Missing/empty selection is a contract violation, not an abstention.
            raise MalformedResponse(
                "answers.selection has no usable 'choice'", raw=text[:2000]
            )

        model = document.get("model")
        model = model if isinstance(model, str) and model else None
        version_match = _VERSION_RE.search(model) if model else None

        probabilities = ranked_probabilities(selection)
        confidence = answer_confidence(selection)
        if confidence is None and probabilities:
            confidence = probabilities[0][1]

        return EngineAnswer(
            selected_option=option.strip(),
            confidence=confidence,
            # Laya does not generate text: no rationale exists to report.
            rationale=None,
            model=model,
            model_version=version_match.group(1) if version_match else None,
            latency_ms=latency_ms,
            usage=Usage.from_mapping(document.get("usage")),
            probabilities=dict(probabilities),
            raw=document,
        )


def _detail(text: str) -> str:
    try:
        document = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return (text or "<empty body>")[:300]
    if isinstance(document, dict) and isinstance(document.get("detail"), list):
        parts = []
        for item in document["detail"]:
            parts.append(str(item.get("msg", item)) if isinstance(item, dict) else str(item))
        return "; ".join(parts) or str(document)[:300]
    return str(document)[:300]


def _detail_list(text: str) -> list[Any]:
    try:
        document = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    if isinstance(document, dict) and isinstance(document.get("detail"), list):
        return list(document["detail"])
    return []
