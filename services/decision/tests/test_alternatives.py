"""Stage 2 requirement 3, reconciled: the ranked alternatives must reach the caller.

``stage2.md`` and ``overview.txt`` both require the engine's probability
distribution to survive onto the public envelope. It did not: ``validate_answer``
built the ``DecisionEnvelope`` from every other field and never read
``answer.probabilities``, and ``validate_envelope`` had no branch for the
corresponding key. This module is the regression coverage for that omission.

Every fixture is deterministic -- no model, no network, no paid inference -- so
this runs in the ordinary offline suite. The real-Laya path is covered by
``integration/test_laya_real.py``.
"""

from __future__ import annotations

import json
import math

import pytest

from layasdlc import (
    Alternative,
    DeterministicEngine,
    EngineAnswer,
    EngineRequest,
    FakeEngine,
    MalformedDecision,
    OutOfScopeOption,
    Outcome,
    SCHEMA_VERSION,
    ToolPermissionPolicy,
    Usage,
    WorkflowController,
    validate_answer,
    validate_envelope,
)

TASK_OPTIONS = ("bug_fix", "feature", "refactor", "testing",
                "documentation", "investigation")


def request(options=TASK_OPTIONS, decision_type="task_classification") -> EngineRequest:
    return EngineRequest(
        decision_id="d1", task_id="T-1", decision_type=decision_type,
        allowed_options=tuple(options), state={"subject": "x"}, question="q",
    )


def answer(selected="bug_fix", *, probabilities=None) -> EngineAnswer:
    return EngineAnswer(
        selected_option=selected,
        confidence=0.9,
        model="fake/laya",
        model_version="0.0-test",
        latency_ms=1.0,
        usage=Usage(input_tokens=10, output_tokens=0),
        probabilities={} if probabilities is None else probabilities,
    )


def ranked(envelope) -> list[tuple[str, float]]:
    assert envelope.alternatives is not None
    return [(alt.option, alt.probability) for alt in envelope.alternatives]


# --- a real distribution survives untouched ---------------------------------------------


def test_a_valid_distribution_reaches_the_envelope_unchanged_in_meaning():
    reported = {"bug_fix": 0.1551, "feature": 0.0397, "refactor": 0.2187,
                "testing": 0.114, "documentation": 0.0628, "investigation": 0.4096}

    envelope = validate_answer(request(), answer(probabilities=dict(reported)))

    assert dict(ranked(envelope)) == reported, (
        "the distribution must reach the caller with its values intact -- no "
        "rescaling, rounding, renormalising or dropping"
    )


def test_alternatives_are_ranked_best_first():
    envelope = validate_answer(
        request(),
        answer(probabilities={"bug_fix": 0.2, "feature": 0.7, "testing": 0.1}),
    )
    assert ranked(envelope) == [("feature", 0.7), ("bug_fix", 0.2), ("testing", 0.1)]


def test_probabilities_are_returned_as_alternative_objects_not_a_bare_map():
    envelope = validate_answer(
        request(), answer(probabilities={"bug_fix": 0.6, "feature": 0.4})
    )
    assert all(isinstance(alt, Alternative) for alt in envelope.alternatives)
    assert [alt.option for alt in envelope.alternatives] == ["bug_fix", "feature"]


# --- selected_option behaviour is untouched ----------------------------------------------


def test_selected_option_still_validates_the_same_way_with_alternatives_present():
    envelope = validate_answer(
        request(), answer("investigation", probabilities={"investigation": 1.0})
    )
    assert envelope.selected_option == "investigation"
    assert envelope.selected_option in envelope.allowed_options
    assert envelope.confidence == 0.9, "confidence handling is unchanged"


def test_an_out_of_scope_selection_is_still_rejected_before_alternatives_matter():
    with pytest.raises(OutOfScopeOption):
        validate_answer(request(), answer("chore", probabilities={"chore": 1.0}))


def test_selected_option_appears_among_the_alternatives_it_was_chosen_from():
    envelope = validate_answer(
        request(),
        answer("bug_fix", probabilities={"bug_fix": 0.5, "feature": 0.3,
                                         "refactor": 0.2}),
    )
    assert envelope.selected_option in [alt.option for alt in envelope.alternatives]
    # ...and is the argmax, which is what "the model picked this" means.
    assert ranked(envelope)[0][0] == "bug_fix"


# --- absence is null, never an empty list -------------------------------------------------


@pytest.mark.parametrize("probabilities", [None, {}])
def test_missing_probabilities_serialise_as_null_not_an_empty_list(probabilities):
    envelope = validate_answer(request(), answer(probabilities=probabilities))

    assert envelope.alternatives is None
    payload = json.loads(json.dumps(envelope.to_dict()))
    assert payload["alternatives"] is None, (
        "absent must be null; [] would claim the model ranked nothing"
    )


def test_an_empty_mapping_is_not_reported_as_an_empty_ranking():
    envelope = validate_answer(request(), answer(probabilities={}))
    assert envelope.alternatives is None
    assert envelope.to_dict()["alternatives"] is None


# --- degenerate but genuine distributions ------------------------------------------------


def test_a_single_valid_alternative_is_handled_correctly():
    envelope = validate_answer(
        request(options=("read_investigate",), decision_type="workflow_selection"),
        answer("read_investigate", probabilities={"read_investigate": 0.87}),
    )

    assert ranked(envelope) == [("read_investigate", 0.87)]
    payload = envelope.to_dict()
    assert payload["alternatives"] == [{"option": "read_investigate",
                                        "probability": 0.87}]


def test_a_zero_probability_is_a_valid_member_of_a_distribution():
    envelope = validate_answer(
        request(), answer(probabilities={"bug_fix": 0.5, "feature": 0.5,
                                         "testing": 0.0})
    )
    assert ("testing", 0.0) in ranked(envelope)


def test_equal_probabilities_order_deterministically_by_option_name():
    tied = {"testing": 0.33, "feature": 0.33, "bug_fix": 0.34, "refactor": 0.33}

    first = ranked(validate_answer(request(), answer(probabilities=dict(tied))))

    # Input order must not leak into the output: the same distribution given in
    # a different key order produces the same envelope.
    shuffled = {"refactor": 0.33, "bug_fix": 0.34, "testing": 0.33, "feature": 0.33}
    second = ranked(validate_answer(request(), answer(probabilities=shuffled)))

    assert first == second
    assert first == [("bug_fix", 0.34), ("feature", 0.33), ("refactor", 0.33),
                     ("testing", 0.33)]


# --- malformed distributions follow the rejection policy ---------------------------------


@pytest.mark.parametrize("value", [
    -0.1,            # negative
    1.5,             # above 1
    math.nan,        # not finite
    math.inf,        # not finite
    -math.inf,       # not finite
    True,            # bool is an int in Python; would read as 1.0
    "0.5",           # a string is not a probability
    None,            # an entry, not a value
])
def test_malformed_probability_values_are_rejected_not_repaired(value):
    with pytest.raises(MalformedDecision):
        validate_answer(request(), answer(probabilities={"bug_fix": value,
                                                         "feature": 0.5}))


def test_a_malformed_entry_does_not_get_dropped_from_an_otherwise_valid_map():
    """Silently removing the bad entry would publish a hand-edited distribution."""
    with pytest.raises(MalformedDecision):
        validate_answer(
            request(),
            answer(probabilities={"bug_fix": 0.5, "feature": float("nan")}),
        )


def test_non_mapping_probabilities_are_rejected():
    with pytest.raises(MalformedDecision):
        validate_answer(request(), answer(probabilities=[0.5, 0.5]))
    with pytest.raises(MalformedDecision):
        validate_answer(request(), answer(probabilities="0.9"))


def test_a_probability_for_an_unoffered_option_is_out_of_scope():
    """A distribution over options the caller never offered answers a different question."""
    with pytest.raises(OutOfScopeOption) as excinfo:
        validate_answer(
            request(options=("bug_fix", "feature")),
            answer(probabilities={"bug_fix": 0.5, "chore": 0.5}),
        )
    assert "chore" in str(excinfo.value)


def test_key_whitespace_is_normalised_before_the_scope_check():
    envelope = validate_answer(
        request(options=("bug_fix",)), answer(probabilities={" bug_fix ": 1.0})
    )
    assert ranked(envelope) == [("bug_fix", 1.0)]


def test_engine_side_normalisation_drops_what_it_cannot_parse_before_validation():
    """Pinning the boundary between *normalisation* and *enforcement*.

    ``ranked_probabilities`` -- shared by both real engines -- discards entries
    it cannot parse (NaN, inf, bool, non-numeric) and passes the rest on, which
    is the same treatment ``answer_confidence`` gives a bad confidence: absent,
    not invented. Validation is what enforces the invariant on whatever reaches
    it, as ``test_a_malformed_entry_does_not_get_dropped_from_an_otherwise_valid_map``
    proves.

    Making the normaliser raise instead would raise from inside
    ``engine.decide()``, where the controller classifies it as an engine/transport
    failure rather than a rejection. That is a different change with a different
    answer, so it is recorded here rather than smuggled into this one.
    """
    from layasdlc.engine import ranked_probabilities

    pairs = ranked_probabilities(
        {"probabilities": {"bug_fix": float("nan"), "feature": 0.4, "refactor": True}}
    )
    assert [label for label, _ in pairs] == ["feature"]

    # Out-of-range values are *not* filtered -- they survive to validation and
    # are rejected there, which is where the decision to refuse is made.
    surviving = dict(ranked_probabilities(
        {"probabilities": {"bug_fix": 1.5, "feature": 0.4}}))
    assert surviving["bug_fix"] == 1.5
    with pytest.raises(MalformedDecision):
        validate_answer(request(), answer(probabilities=surviving))


# --- serialisation and round-tripping -----------------------------------------------------


def test_alternatives_serialise_with_exactly_the_alternative_field_names():
    payload = json.loads(json.dumps(
        validate_answer(request(),
                        answer(probabilities={"bug_fix": 0.6, "feature": 0.4}))
        .to_dict()
    ))
    assert [list(entry) for entry in payload["alternatives"]] == [
        ["option", "probability"], ["option", "probability"]
    ]


def test_round_tripping_through_validate_envelope_preserves_the_alternatives():
    original = validate_answer(
        request(),
        answer("investigation",
               probabilities={"investigation": 0.6, "refactor": 0.4}),
    )

    restored = validate_envelope(original.to_dict())

    assert restored == original
    assert ranked(restored) == ranked(original)


def test_an_empty_list_crossing_the_boundary_normalises_to_null():
    payload = validate_answer(
        request(), answer(probabilities={"bug_fix": 1.0})
    ).to_dict()
    payload["alternatives"] = []

    assert validate_envelope(payload).alternatives is None


def test_a_tampered_alternatives_list_is_rejected_on_the_way_back_in():
    payload = validate_answer(
        request(), answer(probabilities={"bug_fix": 1.0})
    ).to_dict()
    payload["alternatives"] = [{"option": "feature", "probability": 1.2}]

    with pytest.raises(MalformedDecision):
        validate_envelope(payload)


def test_a_duplicate_alternative_is_rejected_on_the_way_back_in():
    payload = validate_answer(
        request(), answer(probabilities={"bug_fix": 1.0})
    ).to_dict()
    payload["alternatives"] = [{"option": "bug_fix", "probability": 0.5},
                               {"option": "bug_fix", "probability": 0.5}]

    with pytest.raises(MalformedDecision):
        validate_envelope(payload)


def test_an_alternative_outside_allowed_options_is_rejected_on_the_way_back_in():
    payload = validate_answer(
        request(options=("bug_fix", "feature")),
        answer(probabilities={"bug_fix": 0.5, "feature": 0.5}),
    ).to_dict()
    payload["alternatives"] = [{"option": "chore", "probability": 1.0}]

    with pytest.raises(OutOfScopeOption):
        validate_envelope(payload)


def test_alternatives_absent_from_a_legacy_payload_are_accepted_as_null():
    payload = validate_answer(
        request(), answer(probabilities={"bug_fix": 1.0})
    ).to_dict()
    del payload["alternatives"]

    assert validate_envelope(payload).alternatives is None


# --- the schema is versioned, not silently widened ----------------------------------------


def test_the_additive_field_is_carried_under_the_current_schema_version():
    envelope = validate_answer(request(), answer(probabilities={"bug_fix": 1.0}))
    assert envelope.schema_version == SCHEMA_VERSION
    assert "alternatives" in envelope.to_dict()


# --- compatibility: the engines already in the tree --------------------------------------


def test_the_controller_carries_the_fake_engines_distribution_to_the_caller(
    task_state, config
):
    """Existing fake-engine tests keep working, and the caller now sees the ranking."""
    engine = FakeEngine(default=answer(
        "bug_fix", probabilities={"bug_fix": 0.7, "feature": 0.3}))
    controller = WorkflowController(engine=engine, config=config,
                                    fallback=DeterministicEngine(),
                                    permissions=ToolPermissionPolicy.full())

    result = controller.decide(task_state, "task_classification")

    assert result.outcome is Outcome.DECIDED
    assert result.envelope is not None
    assert [(alt.option, alt.probability) for alt in result.envelope.alternatives] == [
        ("bug_fix", 0.7), ("feature", 0.3)
    ]


def test_the_controller_reports_null_when_the_engine_offered_no_distribution(
    task_state, config
):
    """An engine that only names an option is not credited with a ranking."""
    engine = FakeEngine(default=EngineAnswer(selected_option="bug_fix",
                                             confidence=0.9))
    controller = WorkflowController(engine=engine, config=config,
                                    fallback=DeterministicEngine(),
                                    permissions=ToolPermissionPolicy.full())

    result = controller.decide(task_state, "task_classification")

    assert result.outcome is Outcome.DECIDED
    assert result.envelope is not None
    assert result.envelope.alternatives is None
    assert result.envelope.to_dict()["alternatives"] is None


def test_the_deterministic_baseline_reports_one_pick_rather_than_a_distribution():
    """The baseline's single confidence share is genuine, not a fabricated ranking."""
    baseline = DeterministicEngine()
    req = EngineRequest(
        decision_id="d1", task_id="T-1", decision_type="task_classification",
        allowed_options=TASK_OPTIONS,
        state={"subject": "Fix the crash in the export pipeline"}, question="q",
    )

    envelope = validate_answer(req, baseline.decide(req))

    assert envelope.alternatives is not None
    assert len(envelope.alternatives) == 1, (
        "the baseline has no distribution over the option set -- it reports "
        "exactly one number and must not be padded out to look like one"
    )
    assert envelope.alternatives[0].option == envelope.selected_option
    assert envelope.alternatives[0].probability == pytest.approx(envelope.confidence)
