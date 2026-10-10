"""Shared fixtures. Every unit test runs offline against a fake engine
(development rule: tests must never need paid inference or a downloaded model).
"""

from __future__ import annotations

import pytest

from layasdlc import (
    ControllerConfig,
    DeterministicEngine,
    FakeEngine,
    PolicyConfig,
    TaskState,
    ToolPermissionPolicy,
    WorkflowController,
)
from layasdlc.engines.fake import answer

TASK_OPTIONS = ("bug_fix", "feature", "refactor", "testing",
                "documentation", "investigation")


@pytest.fixture
def task_state() -> TaskState:
    return TaskState(
        task_id="T-1",
        subject="Checkout throws 500 on promo code",
        body="Applying any promo code raises a 500 and the trace shows a None "
             "discount. This is a regression from the pricing refactor.",
        path="src/billing/pricing.py",
    )


@pytest.fixture
def fake_engine() -> FakeEngine:
    """A confidently-correct model answer for task classification."""
    return FakeEngine(default=answer(
        "bug_fix", confidence=0.9, allowed=TASK_OPTIONS,
        input_tokens=120, output_tokens=0, model="fake/laya", model_version="0.0-test",
    ))


@pytest.fixture
def config() -> ControllerConfig:
    return ControllerConfig(
        timeout_s=2.0,
        policy=PolicyConfig(min_confidence=0.35, fallback_enabled=True),
    )


@pytest.fixture
def controller(fake_engine, config) -> WorkflowController:
    return WorkflowController(
        engine=fake_engine,
        config=config,
        fallback=DeterministicEngine(),
        permissions=ToolPermissionPolicy.read_only(),
    )
