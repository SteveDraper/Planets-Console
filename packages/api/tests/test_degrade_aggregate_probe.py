"""Unit tests for homogeneous per-axis degrade → aggregate probe."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.degrade_aggregate_probe import (
    probe_degrade_aggregate_rewrites,
    should_run_degrade_aggregate_probe,
    torpedo_id_from_ship_torps_loaded_action_id,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceSolution,
    InferenceSolutionAction,
    InferenceSolutionShipBuild,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.scoring import (
    loaded_ship_torpedo_score_delta_2x,
    ship_construction_score_delta_2x,
)
from api.analytics.military_score_inference.ship_build_combos import (
    ship_build_combo_id,
    ship_build_combo_label,
)
from api.analytics.military_score_inference.ship_build_scoring import (
    ship_build_military_score_delta_2x,
)
from api.models.components import Beam, Engine, Hull, Torpedo
from api.models.game import TurnInfo


def _hull(
    *,
    hull_id: int = 70,
    name: str = "Lizard Cruiser",
    beams: int = 4,
    launchers: int = 3,
    engines: int = 2,
    techlevel: int = 5,
    cost: int = 180,
) -> Hull:
    return Hull(
        id=hull_id,
        name=name,
        tritanium=40,
        duranium=20,
        molybdenum=10,
        fueltank=200,
        crew=100,
        engines=engines,
        mass=120,
        techlevel=techlevel,
        cargo=50,
        fighterbays=0,
        launchers=launchers,
        beams=beams,
        cancloak=False,
        cost=cost,
        special="",
        description="",
        advantage=0,
        isbase=False,
        dur=0,
        tri=0,
        mol=0,
        mc=0,
        parentid=0,
        academy=False,
    )


def _engine(*, engine_id: int, tech: int, cost: int, name: str | None = None) -> Engine:
    return Engine(
        id=engine_id,
        name=name or f"Engine T{tech}",
        cost=cost,
        tritanium=0,
        duranium=0,
        molybdenum=0,
        techlevel=tech,
        warp1=0,
        warp2=0,
        warp3=0,
        warp4=0,
        warp5=0,
        warp6=0,
        warp7=0,
        warp8=0,
        warp9=0,
    )


def _beam(*, beam_id: int, tech: int, cost: int, name: str | None = None) -> Beam:
    return Beam(
        id=beam_id,
        name=name or f"Beam T{tech}",
        cost=cost,
        tritanium=0,
        duranium=0,
        molybdenum=0,
        mass=1,
        techlevel=tech,
        crewkill=1,
        damage=1,
    )


def _torpedo(
    *,
    torp_id: int,
    tech: int,
    launchercost: int,
    torpedocost: int,
    name: str | None = None,
) -> Torpedo:
    return Torpedo(
        id=torp_id,
        fullid=torp_id,
        name=name or f"Torp T{tech}",
        torpedocost=torpedocost,
        launchercost=launchercost,
        tritanium=0,
        duranium=0,
        molybdenum=0,
        mass=1,
        techlevel=tech,
        crewkill=1,
        damage=1,
        combatrange=300,
    )


def _minimal_turn(
    *,
    hulls: list[Hull],
    engines: list[Engine],
    beams: list[Beam],
    torpedos: list[Torpedo],
) -> TurnInfo:
    import json
    from pathlib import Path

    from api.serialization.turn import turn_info_from_json

    assets = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"
    base = turn_info_from_json(json.loads((assets / "turn_sample.json").read_text()))
    return replace(
        base,
        hulls=tuple(hulls),
        engines=tuple(engines),
        beams=tuple(beams),
        torpedos=tuple(torpedos),
    )


def _combo(
    hull: Hull,
    engine: Engine,
    beam: Beam | None,
    torpedo: Torpedo | None,
    *,
    beam_count: int,
    launcher_count: int,
    probability_weight: int = 50,
) -> ShipBuildCombo:
    score = ship_build_military_score_delta_2x(
        hull,
        engine,
        beam,
        torpedo,
        beam_count=beam_count,
        launcher_count=launcher_count,
    )
    combo_id = ship_build_combo_id(
        hull_id=hull.id,
        engine_id=engine.id,
        beam_id=beam.id if beam is not None else None,
        torp_id=torpedo.id if torpedo is not None else None,
        beam_count=beam_count,
        launcher_count=launcher_count,
    )
    label = ship_build_combo_label(
        hull,
        engine,
        beam,
        torpedo,
        beam_count=beam_count,
        launcher_count=launcher_count,
    )
    return ShipBuildCombo(
        combo_id=combo_id,
        hull_id=hull.id,
        engine_id=engine.id,
        beam_id=beam.id if beam is not None else None,
        torp_id=torpedo.id if torpedo is not None else None,
        beam_count=beam_count,
        launcher_count=launcher_count,
        labels=(label,),
        score_delta_2x=score,
        warship_delta=1,
        freighter_delta=0,
        upper_bound=2,
        probability_weight=probability_weight,
    )


def _ammo_action(*, torp_id: int, torpedocost: int, upper: int = 40) -> CandidateAction:
    score = loaded_ship_torpedo_score_delta_2x(torpedocost, count=1)
    return CandidateAction(
        id=f"ship_torps_loaded_{torp_id}",
        label=f"Load Mark ammo {torp_id}",
        score_delta_2x=score,
        upper_bound=upper,
    )


def _ship_build_from_combo(combo: ShipBuildCombo, *, count: int = 1) -> InferenceSolutionShipBuild:
    return InferenceSolutionShipBuild(
        combo_id=combo.combo_id,
        label=combo.labels[0],
        count=count,
        hull_id=combo.hull_id,
        engine_id=combo.engine_id,
        beam_id=combo.beam_id,
        torp_id=combo.torp_id,
        beam_count=combo.beam_count,
        launcher_count=combo.launcher_count,
    )


def _catalog(
    *,
    combos: list[ShipBuildCombo],
    actions: list[CandidateAction],
) -> ActionCatalog:
    return ActionCatalog(
        aggregate_actions=tuple(actions),
        ship_build_combos=tuple(combos),
        probability_buckets_by_action_id={},
        policy_step_id="admit_ship_torpedoes",
        policy_step_index=4,
    )


def _observation(*, military_delta_2x: int, warship_delta: int = 1) -> InferenceObservation:
    return InferenceObservation(
        player_id=2,
        turn=9,
        military_delta_2x=military_delta_2x,
        warship_delta=warship_delta,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=3,
        is_after_ship_limit=False,
    )


def test_should_run_probe_only_on_admit_ship_torpedoes() -> None:
    assert should_run_degrade_aggregate_probe("admit_ship_torpedoes")
    assert not should_run_degrade_aggregate_probe("widen_hulls")
    assert not should_run_degrade_aggregate_probe("full_components")


def test_torpedo_id_parser() -> None:
    assert torpedo_id_from_ship_torps_loaded_action_id("ship_torps_loaded_6") == 6
    assert torpedo_id_from_ship_torps_loaded_action_id("planet_defense_posts_added_total") is None


def test_single_ship_beam_degrade_funds_exact_ammo_count() -> None:
    high = _beam(beam_id=10, tech=5, cost=100, name="Disruptor")
    low = _beam(beam_id=1, tech=1, cost=0, name="Laser")
    engine = _engine(engine_id=1, tech=1, cost=1)
    torp = _torpedo(torp_id=6, tech=5, launchercost=20, torpedocost=35, name="Mark 4")
    hull = _hull(beams=1, launchers=0, engines=1)
    high_combo = _combo(hull, engine, high, None, beam_count=1, launcher_count=0)
    low_combo = _combo(hull, engine, low, None, beam_count=1, launcher_count=0)
    action = _ammo_action(torp_id=6, torpedocost=35)
    assert action.score_delta_2x == 100
    assert high_combo.score_delta_2x - low_combo.score_delta_2x == 200

    military = high_combo.score_delta_2x
    catalog = _catalog(combos=[high_combo, low_combo], actions=[action])
    turn = _minimal_turn(hulls=[hull], engines=[engine], beams=[high, low], torpedos=[torp])
    held = InferenceSolution(
        objective_value=-50,
        actions=(),
        ship_builds=(_ship_build_from_combo(high_combo),),
    )
    observation = _observation(military_delta_2x=military)

    rewrites = probe_degrade_aggregate_rewrites(
        [held],
        turn=turn,
        observation=observation,
        catalog=catalog,
    )
    assert len(rewrites) == 1
    rewrite = rewrites[0]
    assert rewrite.actions[0].action_id == "ship_torps_loaded_6"
    assert rewrite.actions[0].count == 2
    assert rewrite.ship_builds[0].combo_id == low_combo.combo_id
    assert not rewrite.ship_builds[0].combo_id.startswith("degrade_probe:")
    assert low_combo.score_delta_2x + action.score_delta_2x * rewrite.actions[0].count == military


def test_two_ship_gap_funding() -> None:
    high = _beam(beam_id=10, tech=5, cost=50, name="Heavy")
    low = _beam(beam_id=1, tech=1, cost=0, name="Light")
    engine = _engine(engine_id=1, tech=1, cost=1)
    torp = _torpedo(torp_id=6, tech=5, launchercost=20, torpedocost=35)
    hull_a = _hull(hull_id=70, name="LCC", beams=1, launchers=0, engines=1)
    hull_b = _hull(hull_id=47, name="Eros", beams=1, launchers=0, engines=1)
    high_a = _combo(hull_a, engine, high, None, beam_count=1, launcher_count=0)
    low_a = _combo(hull_a, engine, low, None, beam_count=1, launcher_count=0)
    high_b = _combo(hull_b, engine, high, None, beam_count=1, launcher_count=0)
    low_b = _combo(hull_b, engine, low, None, beam_count=1, launcher_count=0)
    action = _ammo_action(torp_id=6, torpedocost=35)
    military = high_a.score_delta_2x + high_b.score_delta_2x
    catalog = _catalog(
        combos=[high_a, low_a, high_b, low_b],
        actions=[action],
    )
    turn = _minimal_turn(
        hulls=[hull_a, hull_b],
        engines=[engine],
        beams=[high, low],
        torpedos=[torp],
    )
    held = InferenceSolution(
        objective_value=0,
        actions=(),
        ship_builds=(
            _ship_build_from_combo(high_a),
            _ship_build_from_combo(high_b),
        ),
    )
    rewrites = probe_degrade_aggregate_rewrites(
        [held],
        turn=turn,
        observation=_observation(military_delta_2x=military, warship_delta=2),
        catalog=catalog,
    )
    assert rewrites
    rewrite = rewrites[0]
    assert rewrite.actions[0].count == 2
    assert {sb.combo_id for sb in rewrite.ship_builds} == {low_a.combo_id, low_b.combo_id}


def test_lizard_shaped_lcc_eros_launcher_degrade_funds_mk4_ammo() -> None:
    high_tube = _torpedo(torp_id=10, tech=10, launchercost=100, torpedocost=50, name="Heavy Tube")
    mk4 = _torpedo(torp_id=6, tech=5, launchercost=0, torpedocost=35, name="Mark 4 Photon")
    engine = _engine(engine_id=1, tech=6, cost=10, name="Transwarp")
    beam = _beam(beam_id=5, tech=5, cost=10, name="Disruptor")
    lcc = _hull(hull_id=70, name="Lizard Class Cruiser", beams=4, launchers=3, engines=2)
    eros = _hull(hull_id=47, name="Eros Class", beams=2, launchers=0, engines=1)
    held_lcc = _combo(lcc, engine, beam, high_tube, beam_count=4, launcher_count=1)
    rewritten_lcc = _combo(lcc, engine, beam, mk4, beam_count=4, launcher_count=1)
    eros_combo = _combo(eros, engine, beam, None, beam_count=2, launcher_count=0)
    action = _ammo_action(torp_id=6, torpedocost=35)
    military = held_lcc.score_delta_2x + eros_combo.score_delta_2x
    catalog = _catalog(
        combos=[held_lcc, rewritten_lcc, eros_combo],
        actions=[action],
    )
    turn = _minimal_turn(
        hulls=[lcc, eros],
        engines=[engine],
        beams=[beam],
        torpedos=[high_tube, mk4],
    )
    held = InferenceSolution(
        objective_value=-100,
        actions=(),
        ship_builds=(
            _ship_build_from_combo(held_lcc),
            _ship_build_from_combo(eros_combo),
        ),
    )
    rewrites = probe_degrade_aggregate_rewrites(
        [held],
        turn=turn,
        observation=_observation(military_delta_2x=military, warship_delta=2),
        catalog=catalog,
    )
    assert rewrites
    rewrite = rewrites[0]
    assert rewrite.actions[0].action_id == "ship_torps_loaded_6"
    assert rewrite.actions[0].count >= 1
    assert rewrite.ship_builds[0].combo_id == rewritten_lcc.combo_id
    assert all(not sb.combo_id.startswith("degrade_probe:") for sb in rewrite.ship_builds)


def test_noop_when_no_tech_le_downgrade_funds_aggregate() -> None:
    only = _beam(beam_id=10, tech=5, cost=100)
    engine = _engine(engine_id=1, tech=1, cost=1)
    torp = _torpedo(torp_id=6, tech=5, launchercost=20, torpedocost=35)
    hull = _hull(beams=1, launchers=0, engines=1)
    combo = _combo(hull, engine, only, None, beam_count=1, launcher_count=0)
    action = _ammo_action(torp_id=6, torpedocost=35)
    catalog = _catalog(combos=[combo], actions=[action])
    turn = _minimal_turn(hulls=[hull], engines=[engine], beams=[only], torpedos=[torp])
    held = InferenceSolution(
        objective_value=0,
        actions=(),
        ship_builds=(_ship_build_from_combo(combo),),
    )
    rewrites = probe_degrade_aggregate_rewrites(
        [held],
        turn=turn,
        observation=_observation(military_delta_2x=combo.score_delta_2x),
        catalog=catalog,
    )
    assert rewrites == []


def test_rejects_rewrite_when_catalog_combo_missing() -> None:
    """Degrade target not in catalog must not emit synthetic combo ids."""
    high = _beam(beam_id=10, tech=5, cost=100)
    low = _beam(beam_id=1, tech=1, cost=0)
    engine = _engine(engine_id=1, tech=1, cost=1)
    torp = _torpedo(torp_id=6, tech=5, launchercost=20, torpedocost=35)
    hull = _hull(beams=1, launchers=0, engines=1)
    high_combo = _combo(hull, engine, high, None, beam_count=1, launcher_count=0)
    # Intentionally omit low_combo from catalog.
    action = _ammo_action(torp_id=6, torpedocost=35)
    catalog = _catalog(combos=[high_combo], actions=[action])
    turn = _minimal_turn(hulls=[hull], engines=[engine], beams=[high, low], torpedos=[torp])
    # Eligible beams come from catalog only -- low is absent, so no variants.
    # Force a path where turn has low but catalog does not: still no rewrite.
    held = InferenceSolution(
        objective_value=0,
        actions=(),
        ship_builds=(_ship_build_from_combo(high_combo),),
    )
    rewrites = probe_degrade_aggregate_rewrites(
        [held],
        turn=turn,
        observation=_observation(military_delta_2x=high_combo.score_delta_2x),
        catalog=catalog,
    )
    assert rewrites == []


def test_skips_solutions_that_already_have_aggregates() -> None:
    high = _beam(beam_id=10, tech=5, cost=100)
    low = _beam(beam_id=1, tech=1, cost=0)
    engine = _engine(engine_id=1, tech=1, cost=1)
    torp = _torpedo(torp_id=6, tech=5, launchercost=20, torpedocost=35)
    hull = _hull(beams=1, launchers=0, engines=1)
    high_combo = _combo(hull, engine, high, None, beam_count=1, launcher_count=0)
    low_combo = _combo(hull, engine, low, None, beam_count=1, launcher_count=0)
    action = _ammo_action(torp_id=6, torpedocost=35)
    pd = CandidateAction(
        id="planet_defense_posts_added_total",
        label="PD",
        score_delta_2x=11,
        upper_bound=100,
    )
    catalog = _catalog(combos=[high_combo, low_combo], actions=[action, pd])
    turn = _minimal_turn(hulls=[hull], engines=[engine], beams=[high, low], torpedos=[torp])
    held = InferenceSolution(
        objective_value=0,
        actions=(InferenceSolutionAction(action_id=pd.id, label=pd.label, count=1),),
        ship_builds=(_ship_build_from_combo(high_combo),),
    )
    assert (
        probe_degrade_aggregate_rewrites(
            [held],
            turn=turn,
            observation=_observation(
                military_delta_2x=high_combo.score_delta_2x + pd.score_delta_2x
            ),
            catalog=catalog,
        )
        == []
    )


def test_homogeneous_axis_emits_single_beam_id_per_ship() -> None:
    high = _beam(beam_id=10, tech=5, cost=100)
    mid = _beam(beam_id=5, tech=3, cost=40)
    low = _beam(beam_id=1, tech=1, cost=0)
    engine = _engine(engine_id=1, tech=1, cost=1)
    torp = _torpedo(torp_id=6, tech=5, launchercost=20, torpedocost=35)
    hull = _hull(beams=4, launchers=0, engines=1)
    combos = [
        _combo(hull, engine, beam, None, beam_count=4, launcher_count=0)
        for beam in (high, mid, low)
    ]
    action = _ammo_action(torp_id=6, torpedocost=35)
    military = combos[0].score_delta_2x
    catalog = _catalog(combos=combos, actions=[action])
    turn = _minimal_turn(hulls=[hull], engines=[engine], beams=[high, mid, low], torpedos=[torp])
    held = InferenceSolution(
        objective_value=0,
        actions=(),
        ship_builds=(_ship_build_from_combo(combos[0]),),
    )
    rewrites = probe_degrade_aggregate_rewrites(
        [held],
        turn=turn,
        observation=_observation(military_delta_2x=military),
        catalog=catalog,
    )
    assert rewrites
    for rewrite in rewrites:
        for ship_build in rewrite.ship_builds:
            assert ship_build.beam_id in {high.id, mid.id, low.id}
            assert ship_build.beam_count == 4
            assert not ship_build.combo_id.startswith("degrade_probe:")


# Keep scoring helper import referenced for gap arithmetic assertions above.
_ = ship_construction_score_delta_2x
