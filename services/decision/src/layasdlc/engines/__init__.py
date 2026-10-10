"""Engine implementations behind :class:`layasdlc.engine.DecisionEngine`.

Four implementations, one interface (Stage 2 requirement 9):

* :class:`~layasdlc.engines.fake.FakeEngine` -- scripted answers for unit tests;
  no network, no model, fully deterministic;
* :class:`~layasdlc.engines.deterministic.DeterministicEngine` -- keyword
  baseline: the fallback target *and* the comparison point (Stage 1 feature 6);
* :class:`~layasdlc.engines.laya_http.LayaHttpEngine` -- **real Laya** over the
  Jev-compatible ``POST /v1/systemone`` wire protocol;
* :class:`~layasdlc.engines.laya_sdk.LayaSdkEngine` -- **real Laya** through the
  local ``laya`` Python package, when it is installed.
"""

from __future__ import annotations

from .deterministic import DeterministicEngine, score_state
from .fake import FakeEngine, Scripted
from .laya_http import LayaHttpEngine, RawResponse, Transport, UrllibTransport
from .laya_sdk import LayaSdkEngine, laya_sdk_available

__all__ = [
    "FakeEngine",
    "Scripted",
    "DeterministicEngine",
    "score_state",
    "LayaHttpEngine",
    "UrllibTransport",
    "RawResponse",
    "Transport",
    "LayaSdkEngine",
    "laya_sdk_available",
]
