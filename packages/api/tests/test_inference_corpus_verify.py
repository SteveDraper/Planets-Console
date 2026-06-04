"""Unit tests for Tier 1 independent constraint re-check."""

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.models import CandidateAction, InferenceObservation

from tests.inference_corpus.verify import verify_top_solution_hard_equalities


def _observation(**overrides: int) -> InferenceObservation:
    defaults = {
        "player_id": 1,
        "turn": 3,
        "military_delta_2x": 250,
        "warship_delta": 0,
        "freighter_delta": 0,
        "priority_point_delta": 0,
        "starbases_owned": 1,
        "is_after_ship_limit": False,
    }
    defaults.update(overrides)
    return InferenceObservation(**defaults)


def _catalog(*actions: CandidateAction) -> ActionCatalog:
    return ActionCatalog(actions=actions, probability_buckets_by_action_id={})


def _payload(*, actions: list[object]) -> dict[str, object]:
    return {"solutions": [{"actions": list(actions)}]}


def test_verify_passes_when_top_solution_matches_observation():
    action = CandidateAction(
        id="ship_fighters_added_total",
        label="fighters",
        score_delta_2x=250,
    )
    observation = _observation(military_delta_2x=250)
    error = verify_top_solution_hard_equalities(
        observation=observation,
        catalog=_catalog(action),
        inference_payload=_payload(actions=[{"actionId": "ship_fighters_added_total", "count": 1}]),
    )
    assert error is None


def test_verify_rejects_non_object_action_entry():
    observation = _observation()
    error = verify_top_solution_hard_equalities(
        observation=observation,
        catalog=_catalog(),
        inference_payload=_payload(actions=["not-an-object"]),
    )
    assert error == "top solution actions[0] must be an object, got str"


def test_verify_rejects_missing_action_id():
    observation = _observation()
    error = verify_top_solution_hard_equalities(
        observation=observation,
        catalog=_catalog(),
        inference_payload=_payload(actions=[{"count": 1}]),
    )
    assert error == "top solution actions[0].actionId must be a non-empty string"


def test_verify_rejects_non_positive_count():
    observation = _observation()
    error = verify_top_solution_hard_equalities(
        observation=observation,
        catalog=_catalog(),
        inference_payload=_payload(actions=[{"actionId": "ship_fighters_added_total", "count": 0}]),
    )
    assert error == "top solution actions[0].count must be positive, got 0"
