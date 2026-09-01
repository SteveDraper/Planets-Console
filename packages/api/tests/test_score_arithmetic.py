from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceSolution,
    InferenceSolutionAction,
    InferenceSolutionShipBuild,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.score_arithmetic import (
    solution_military_score_arithmetic_payload,
)


def _observation(*, military_delta_2x: int, slack: int = 0) -> InferenceObservation:
    return InferenceObservation(
        player_id=5,
        turn=15,
        military_delta_2x=military_delta_2x,
        warship_delta=3,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=2,
        is_after_ship_limit=False,
        military_partition_slack_2x=slack,
    )


def _acquired(*, max_2x: int) -> CandidateAction:
    return CandidateAction(
        id="acquired:warship:from:1",
        label="Acquired warship from player 1",
        score_delta_2x=0,
        warship_delta=1,
        score_delta_2x_min=0,
        score_delta_2x_max=max_2x,
        counterparty_player_id=1,
        upper_bound=1,
    )


def _combo(*, combo_id: str, score_delta_2x: int) -> ShipBuildCombo:
    return ShipBuildCombo(
        combo_id=combo_id,
        hull_id=24,
        engine_id=9,
        beam_id=10,
        torp_id=10,
        beam_count=4,
        launcher_count=4,
        labels=("Meteor",),
        score_delta_2x=score_delta_2x,
        warship_delta=1,
        build_slot_usage=1,
        upper_bound=2,
    )


def test_interval_action_tightens_to_leftover_after_point_combos():
    meteor_2x = 4176
    observed_2x = 13348
    leftover_2x = observed_2x - 2 * meteor_2x
    acquired = _acquired(max_2x=observed_2x)
    combo = _combo(combo_id="combo_meteor", score_delta_2x=meteor_2x)
    solution = InferenceSolution(
        objective_value=1,
        actions=(
            InferenceSolutionAction(
                action_id=acquired.id,
                label=acquired.label,
                count=1,
                counterparty_player_id=1,
            ),
        ),
        ship_builds=(
            InferenceSolutionShipBuild(
                combo_id=combo.combo_id,
                label="Meteor",
                count=2,
            ),
        ),
    )
    arithmetic = solution_military_score_arithmetic_payload(
        solution,
        _observation(military_delta_2x=observed_2x),
        {acquired.id: acquired},
        {combo.combo_id: combo},
    )
    acquired_line = arithmetic["lineItems"][0]
    meteor_line = arithmetic["lineItems"][1]
    assert meteor_line["scoreDelta2xSubtotal"] == 2 * meteor_2x
    assert acquired_line["scoreDelta2xSubtotal"] == leftover_2x
    assert acquired_line["militaryChangeSubtotal"] == leftover_2x // 2
    assert "scoreDelta2xSubtotalMin" not in acquired_line
    assert arithmetic["explainedMilitaryDelta2x"] == observed_2x
    assert arithmetic["matchesObserved"] is True


def test_interval_action_keeps_floor_slack_band_on_leftover():
    meteor_2x = 4176
    observed_2x = 13348
    leftover_2x = observed_2x - 2 * meteor_2x
    acquired = _acquired(max_2x=observed_2x)
    combo = _combo(combo_id="combo_meteor", score_delta_2x=meteor_2x)
    solution = InferenceSolution(
        objective_value=1,
        actions=(
            InferenceSolutionAction(
                action_id=acquired.id,
                label=acquired.label,
                count=1,
            ),
        ),
        ship_builds=(InferenceSolutionShipBuild(combo_id=combo.combo_id, label="Meteor", count=2),),
    )
    arithmetic = solution_military_score_arithmetic_payload(
        solution,
        _observation(military_delta_2x=observed_2x, slack=1),
        {acquired.id: acquired},
        {combo.combo_id: combo},
    )
    acquired_line = next(
        item for item in arithmetic["lineItems"] if item.get("actionId") == acquired.id
    )
    assert acquired_line["scoreDelta2xSubtotal"] == leftover_2x
    assert acquired_line["scoreDelta2xSubtotalMin"] == leftover_2x - 1
    assert acquired_line["scoreDelta2xSubtotalMax"] == leftover_2x + 1
    assert arithmetic["matchesObserved"] is True


def test_two_interval_actions_share_leftover_without_overlapping_catalog_width():
    observed_2x = 100
    first = CandidateAction(
        id="acquired:warship:from:1",
        label="Acquired warship from player 1",
        score_delta_2x=0,
        score_delta_2x_min=0,
        score_delta_2x_max=40,
        upper_bound=1,
    )
    second = CandidateAction(
        id="loss:warship:envelope:0:100",
        label="Ship loss (warship, envelope 0-100)",
        score_delta_2x=0,
        score_delta_2x_min=0,
        score_delta_2x_max=100,
        upper_bound=1,
    )
    solution = InferenceSolution(
        objective_value=1,
        actions=(
            InferenceSolutionAction(action_id=first.id, label=first.label, count=1),
            InferenceSolutionAction(action_id=second.id, label=second.label, count=1),
        ),
    )
    arithmetic = solution_military_score_arithmetic_payload(
        solution,
        _observation(military_delta_2x=observed_2x),
        {first.id: first, second.id: second},
    )
    lines = {item["actionId"]: item for item in arithmetic["lineItems"]}
    assert lines[first.id]["scoreDelta2xSubtotalMin"] == 0
    assert lines[first.id]["scoreDelta2xSubtotalMax"] == 40
    assert lines[second.id]["scoreDelta2xSubtotalMin"] == 60
    assert lines[second.id]["scoreDelta2xSubtotalMax"] == 100
    assert (
        lines[first.id]["scoreDelta2xSubtotal"] + lines[second.id]["scoreDelta2xSubtotal"]
        == observed_2x
    )
    assert arithmetic["matchesObserved"] is True


def test_point_actions_keep_catalog_military_and_can_mismatch():
    action = CandidateAction(id="starbase_fighter", label="Starbase fighter", score_delta_2x=125)
    solution = InferenceSolution(
        objective_value=1,
        actions=(InferenceSolutionAction(action_id=action.id, label=action.label, count=1),),
    )
    arithmetic = solution_military_score_arithmetic_payload(
        solution,
        _observation(military_delta_2x=100),
        {action.id: action},
    )
    assert arithmetic["matchesObserved"] is False
    assert arithmetic["lineItems"][0]["scoreDelta2xSubtotal"] == 125
    assert "scoreDelta2xSubtotalMin" not in arithmetic["lineItems"][0]
