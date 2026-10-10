"""Real Laya through the local ``laya`` Python package (optional second path).

Verified against ``laya`` 0.4.2 source before this module was written:

* ``laya.load(model_id_or_path="convaiinnovations/laya", device=None, ...,
  subfolder=None, ...) -> Agent`` -- the only supported way to obtain an agent;
* ``Agent.system_one(state, questions, *, lang=None, min_confidence=None, ...)
  -> Dict[str, Any]`` -- answers typed questions in one forward pass;
* question types are exactly ``choice`` / ``score`` / ``noul``;
* ``import laya`` is cheap: the torch-backed names are lazy, so merely probing
  for the package never pays torch's import time.

Availability is honest. :meth:`available` reports whether the package is
*importable* without loading weights (a health check must not download 808 MB),
and :meth:`probe` performs the real check. On this host the package is **not**
installed, so the integration test skips rather than pretending to succeed.
"""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass, field
from typing import Any, Optional

from ..contracts import Usage
from ..engine import EngineAnswer, EngineRequest, answer_confidence, ranked_probabilities
from ..errors import EngineFailure, EngineUnavailable
from ..questions import question_for

DEFAULT_REPO = "convaiinnovations/laya"


def laya_sdk_available() -> bool:
    """True when the ``laya`` package can be found. Does not import it."""
    try:
        return importlib.util.find_spec("laya") is not None
    except (ImportError, ValueError):
        return False


@dataclass
class LayaSdkEngine:
    """Answers through ``laya.load(...).system_one(...)``.

    Parameters
    ----------
    model_id:
        Registry name, Hub repo id or local path. ``laya.load`` resolves
        aliases such as ``"english"``/``"ml"`` itself.
    subfolder:
        Selects a checkpoint from a bundled repo (``multilingual``,
        ``typed-decisions``).
    device:
        Passed straight to ``laya.load``; ``None`` lets Laya choose.
    """

    model_id: str = DEFAULT_REPO
    subfolder: Optional[str] = None
    device: Optional[str] = None
    name: str = "laya-sdk"
    version: Optional[str] = None
    _agent: Any = field(default=None, init=False, repr=False)

    def available(self) -> bool:
        """Importability probe only -- never loads weights."""
        return laya_sdk_available()

    def probe(self) -> dict[str, Any]:
        """Real readiness check: import the package and report its version."""
        if not laya_sdk_available():
            return {"reachable": False,
                    "detail": "package 'laya' is not installed in this environment"}
        try:
            laya = importlib.import_module("laya")
            return {"reachable": True,
                    "detail": {"version": getattr(laya, "__version__", "unknown"),
                               "weights_loaded": self._agent is not None}}
        except Exception as exc:  # noqa: BLE001 - import failure is a reportable finding
            return {"reachable": False, "detail": f"{type(exc).__name__}: {exc}"}

    def decide(self, request: EngineRequest) -> EngineAnswer:
        if not laya_sdk_available():
            raise EngineUnavailable(
                "the 'laya' Python package is not installed; "
                "install it with `pip install laya` or use LayaHttpEngine"
            )

        questions = question_for(request.decision_type, request.allowed_options)
        agent = self._load()

        try:
            result = agent.system_one(dict(request.state), questions)
        except Exception as exc:  # noqa: BLE001 - surfaced as a typed engine failure
            raise EngineFailure(f"laya system_one failed: {type(exc).__name__}: {exc}") from exc

        if not isinstance(result, dict):
            raise EngineFailure(f"laya returned {type(result).__name__}, expected dict")

        answers = result.get("answers")
        if not isinstance(answers, dict):
            raise EngineFailure("laya response has no 'answers' object")

        selection = answers.get("selection")
        if not isinstance(selection, dict):
            raise EngineFailure("laya response has no 'answers.selection' object")

        option = selection.get("choice")
        if not isinstance(option, str) or not option.strip():
            raise EngineFailure("laya answers.selection has no usable 'choice'")

        model = result.get("model")
        model = model if isinstance(model, str) and model else self.model_id

        probabilities = ranked_probabilities(selection)
        confidence = answer_confidence(selection)
        if confidence is None and probabilities:
            confidence = probabilities[0][1]

        return EngineAnswer(
            selected_option=option.strip(),
            confidence=confidence,
            # Laya never generates text; there is no rationale to report.
            rationale=None,
            model=model,
            model_version=self._package_version(),
            latency_ms=None,          # measured by the controller, not trusted from the SDK
            usage=Usage.from_mapping(result.get("usage")) if result.get("usage") else None,
            probabilities=dict(probabilities),
            raw=result,
        )

    # --- internals ----------------------------------------------------------------------

    def _load(self) -> Any:
        if self._agent is None:
            laya = importlib.import_module("laya")
            try:
                self._agent = laya.load(
                    self.model_id, subfolder=self.subfolder, device=self.device
                )
            except Exception as exc:  # noqa: BLE001 - download/weights/device problems
                raise EngineUnavailable(
                    f"laya.load({self.model_id!r}) failed: {type(exc).__name__}: {exc}"
                ) from exc
            if self.version is None:
                self.version = self._package_version()
        return self._agent

    @staticmethod
    def _package_version() -> Optional[str]:
        try:
            laya = importlib.import_module("laya")
        except Exception:  # noqa: BLE001
            return None
        version = getattr(laya, "__version__", None)
        return str(version) if version else None
