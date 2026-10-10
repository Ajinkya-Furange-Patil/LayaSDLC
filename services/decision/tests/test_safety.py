"""Stage 1 feature 8: destructive and deployment work must be gated deterministically."""

from __future__ import annotations

import pytest

from layasdlc import (
    ApprovalRequiredError,
    PolicyConfig,
    SafetyClass,
    classify_safety,
)
from layasdlc.policy import guard_approval, requires_approval


@pytest.mark.parametrize("text", [
    "Run DROP TABLE orders on the replica to test the migration",
    "Please truncate table sessions before the demo",
    "Delete from users where created_at < 2020",
    "Force push the cleaned-up history to main",
    "rm -rf the build cache directory",
])
def test_destructive_phrases_require_approval(text):
    finding = classify_safety({"body": text})
    assert finding.safety_class is SafetyClass.DESTRUCTIVE
    assert finding.requires_approval is True


@pytest.mark.parametrize("text", [
    "Deploy the new checkout service to production",
    "Roll out the feature flag to all users",
    "Release to prod after the meeting",
    "Publish the package to npm",
    "Ship the hotfix to live",
])
def test_deployment_phrases_require_approval(text):
    finding = classify_safety({"body": text})
    assert finding.safety_class is SafetyClass.DEPLOYMENT
    assert finding.requires_approval is True
    assert finding.matched, "the reason must cite the text that actually triggered"


def test_everyday_work_is_safe_and_needs_no_approval():
    finding = classify_safety({"subject": "Fix NPE", "body": "The parser crashes on empty input."})
    assert finding.safety_class is SafetyClass.SAFE
    assert finding.requires_approval is False
    assert finding.matched == ()


def test_deployment_wins_the_label_when_both_apply_but_both_are_gated():
    finding = classify_safety({"body": "Drop the legacy table, then deploy to production."})
    assert finding.safety_class is SafetyClass.DEPLOYMENT
    assert finding.requires_approval is True
    assert len(finding.matched) >= 2


def test_detector_reads_nested_state_objects():
    assert classify_safety({"body": {"steps": ["truncate table staging_events"]}}).requires_approval


def test_guard_passes_when_approved():
    finding = classify_safety({"body": "deploy to production"})
    guard_approval(finding, PolicyConfig(), approved=True)  # must not raise


def test_guard_passes_for_safe_work_without_approval():
    finding = classify_safety({"body": "fix the typo in the help text"})
    guard_approval(finding, PolicyConfig(), approved=False)  # must not raise


def test_guard_raises_for_unapproved_destructive_work():
    finding = classify_safety({"body": "drop table orders"})
    with pytest.raises(ApprovalRequiredError) as excinfo:
        guard_approval(finding, PolicyConfig(), approved=False)
    assert excinfo.value.requires_approval is True
    assert excinfo.value.safety_class == "destructive"
    assert "drop table" in str(excinfo.value)


def test_approval_gate_is_configurable_by_class():
    """Class membership alone decides -- the detector's flag does not override it."""
    permissive = PolicyConfig(approval_classes=frozenset({SafetyClass.DEPLOYMENT}))
    destructive = classify_safety({"body": "drop table orders"})

    assert destructive.requires_approval is True       # detector still reports a match
    assert requires_approval(destructive, PolicyConfig()) is True
    assert requires_approval(destructive, permissive) is False


def test_the_controller_reports_approval_requirement_without_enforcing_it():
    """Feature 8 is a gate the *caller* must consult before executing."""
    from layasdlc import ControllerConfig, DeterministicEngine, TaskState, WorkflowController

    controller = WorkflowController(engine=DeterministicEngine(),
                                    config=ControllerConfig())
    finding = classify_safety({"body": "drop table staging_events"})
    result = controller.decide(
        TaskState(task_id="T", subject="Clean up", body="drop table staging_events"),
        "task_classification",
    )
    assert result.requires_approval is True
    assert "drop table" in (result.approval_reason or "")

    # The controller reports the requirement; it does not act. Asking to act without
    # approval is what raises.
    with pytest.raises(ApprovalRequiredError):
        guard_approval(finding, PolicyConfig(), approved=False)
