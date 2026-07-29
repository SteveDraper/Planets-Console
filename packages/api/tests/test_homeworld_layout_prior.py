"""Core tests for homeworld layout prior selection and isMostProbable."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.homeworld_locator.baseline_ensure import materialize_homeworld_candidate_view
from api.analytics.homeworld_locator.compute import get_homeworld_locator
from api.analytics.homeworld_locator.constants import ANALYTIC_ID
from api.analytics.homeworld_locator.layout_distributions_asset import (
    CategoryLayoutDistributions,
    LayoutDistributionsAsset,
    SmoothedMetricDistribution,
)
from api.analytics.homeworld_locator.layout_prior import apply_layout_prior_most_probable
from api.analytics.homeworld_locator.models import (
    CONFIDENCE_DEFINITE,
    CONFIDENCE_POSSIBLE,
    OriginDistanceObservation,
)
from api.analytics.homeworld_locator.persistence import HomeworldLocatorPersistenceService
from api.analytics.homeworld_locator.types import (
    HomeworldCandidateRecord,
    HomeworldCandidateView,
    HomeworldEvidenceAggregate,
    HomeworldLocatorGameState,
)
from api.concepts.homeworld_layout import (
    HW_DISTRIBUTION_CIRCULAR,
    HW_DISTRIBUTION_RANDOM_SPACED,
    MAP_SHAPE_ROUND,
    homeworld_settings_fingerprint,
)
from api.models.planet import Planet
from api.serialization.turn import turn_info_from_json
from api.storage.memory_asset import MemoryAssetBackend

from tests.test_homeworld_locator_core import _services as core_services

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def memory_backend():
    return MemoryAssetBackend(initial={})


@pytest.fixture
def persistence(memory_backend):
    return HomeworldLocatorPersistenceService(memory_backend)


@pytest.fixture
def template_planet() -> Planet:
    raw = json.loads((ASSETS_DIR / "turn_sample.json").read_text(encoding="utf-8"))
    turn = turn_info_from_json(raw, settings_defaults=raw["settings"])
    return turn.planets[0]


@pytest.fixture
def sample_turn():
    raw = json.loads((ASSETS_DIR / "turn_sample.json").read_text(encoding="utf-8"))
    return turn_info_from_json(raw, settings_defaults=raw["settings"])


def _planet(
    template: Planet,
    *,
    planet_id: int,
    x: int,
    y: int,
    ownerid: int = 0,
) -> Planet:
    return replace(
        template,
        id=planet_id,
        name=f"P{planet_id}",
        x=x,
        y=y,
        ownerid=ownerid,
        clans=0,
        temp=50,
        debrisdisk=0,
    )


def _linear_metric(*, support_min: float, support_max: float) -> SmoothedMetricDistribution:
    mid = 0.5 * (support_min + support_max)
    return SmoothedMetricDistribution(
        sample_count=100,
        support_min=support_min,
        support_max=support_max,
        mean=mid,
        std=max(1.0, (support_max - support_min) / 6.0),
    )


def _stub_layout_asset(*, support_min: float = 500.0, support_max: float = 600.0):
    metric = _linear_metric(support_min=support_min, support_max=support_max)
    category = CategoryLayoutDistributions(
        center_distance=metric,
        neighbor_separation=metric,
    )
    return LayoutDistributionsAsset(
        schema_version=2,
        bin_width_ly=10.0,
        cost_model="normal_neg_log_density",
        categories={"epic": category, "standard": category},
        source={},
    )


def _eligible_turn(sample_turn, template_planet, *, players: list | None = None):
    player_list = players
    if player_list is None:
        player_list = [
            replace(sample_turn.player, id=index + 1, username=f"p{index + 1}")
            for index in range(11)
        ]
    settings = replace(
        sample_turn.settings,
        turn=1,
        hwdistribution=HW_DISTRIBUTION_CIRCULAR,
        mapshape=MAP_SHAPE_ROUND,
        shiplimit=500,
        endturn=100,
        campaignmode=False,
        planetscanrange=10000,
    )
    pin = _planet(template_planet, planet_id=1, x=2550, y=2000, ownerid=player_list[0].id)
    return replace(
        sample_turn,
        settings=settings,
        player=player_list[0],
        players=player_list,
        planets=[pin],
        ships=[],
        relations=[],
    ), pin


def _materialize_ctx(services, turn, turns: dict[int, object] | None = None):
    from api.analytics.compute_context import make_analytic_compute_context

    stored = turns if turns is not None else {turn.settings.turn: turn}
    return make_analytic_compute_context(
        turn,
        load_turn=lambda n: stored.get(n),
        export_services={ANALYTIC_ID: services},
    ).exports


def _view(*candidates: HomeworldCandidateRecord) -> HomeworldCandidateView:
    return HomeworldCandidateView(
        candidates=candidates,
        baseline_turn=1,
        baseline_degraded=False,
        available=True,
    )


def test_neg_log_density_is_lowest_at_mean() -> None:
    metric = _linear_metric(support_min=100.0, support_max=200.0)
    at_mean = metric.neg_log_density(metric.mean)
    assert metric.neg_log_density(metric.mean - 3 * metric.std) > at_mean
    assert metric.neg_log_density(metric.mean + 3 * metric.std) > at_mean
    assert metric.neg_log_density(metric.mean) == pytest.approx(
        0.5 * math.log(2 * math.pi * metric.std * metric.std)
    )


def test_ineligible_gate_leaves_is_most_probable_false(template_planet, sample_turn) -> None:
    turn, pin = _eligible_turn(sample_turn, template_planet)
    non_circular = replace(
        turn,
        settings=replace(turn.settings, hwdistribution=HW_DISTRIBUTION_RANDOM_SPACED),
    )
    orphan = HomeworldCandidateRecord(
        planet_id=2,
        perspective=None,
        confidence_tier=CONFIDENCE_POSSIBLE,
    )
    definite = HomeworldCandidateRecord(
        planet_id=pin.id,
        perspective=1,
        confidence_tier=CONFIDENCE_DEFINITE,
    )
    view = _view(definite, orphan)
    annotated = apply_layout_prior_most_probable(
        (definite, orphan),
        turn=non_circular,
        view=view,
        player_count=11,
        layout_asset=_stub_layout_asset(),
        map_center=(2000.0, 2000.0),
    )
    assert all(row.is_most_probable is False for row in annotated)


def test_definite_sectors_never_most_probable(template_planet, sample_turn) -> None:
    turn, pin = _eligible_turn(sample_turn, template_planet)
    center = (2000.0, 2000.0)
    radius = 550
    orphan = _planet(template_planet, planet_id=2, x=int(center[0]), y=int(center[1] + radius))
    turn = replace(turn, planets=[pin, orphan])
    definite = HomeworldCandidateRecord(
        planet_id=pin.id,
        perspective=1,
        confidence_tier=CONFIDENCE_DEFINITE,
    )
    possible = HomeworldCandidateRecord(
        planet_id=orphan.id,
        perspective=None,
        confidence_tier=CONFIDENCE_POSSIBLE,
    )
    view = _view(definite, possible)
    annotated = apply_layout_prior_most_probable(
        (definite, possible),
        turn=turn,
        view=view,
        player_count=11,
        layout_asset=_stub_layout_asset(),
        map_center=center,
    )
    by_id = {row.planet_id: row for row in annotated}
    assert by_id[pin.id].is_most_probable is False
    assert by_id[orphan.id].is_most_probable is True
    # Golden parity: definite sectors never contribute most-probable ids.
    assert {row.planet_id for row in annotated if row.is_most_probable} == {orphan.id}


def test_tie_break_prefers_lex_smaller_planet_id(template_planet, sample_turn) -> None:
    turn, _pin = _eligible_turn(sample_turn, template_planet)
    center = (2000.0, 2000.0)
    player_count = 11
    radius = 550.0
    pin_angle = 0.0
    sector_angle = pin_angle + (2.0 * math.pi / player_count)
    pin_planet = _planet(
        template_planet,
        planet_id=1,
        x=int(center[0] + radius * math.cos(pin_angle)),
        y=int(center[1] + radius * math.sin(pin_angle)),
        ownerid=1,
    )
    low_id = _planet(
        template_planet,
        planet_id=2,
        x=int(center[0] + radius * math.cos(sector_angle)),
        y=int(center[1] + radius * math.sin(sector_angle)),
    )
    high_id = _planet(
        template_planet,
        planet_id=9,
        x=int(center[0] + (radius + 15) * math.cos(sector_angle)),
        y=int(center[1] + (radius + 15) * math.sin(sector_angle)),
    )
    turn = replace(
        turn,
        planets=[pin_planet, low_id, high_id],
        ships=[],
    )
    flat_metric = SmoothedMetricDistribution(
        sample_count=1,
        support_min=0.0,
        support_max=1000.0,
        mean=500.0,
        std=1.0e6,
    )
    flat_asset = LayoutDistributionsAsset(
        schema_version=2,
        bin_width_ly=10.0,
        cost_model="normal_neg_log_density",
        categories={
            "epic": CategoryLayoutDistributions(
                center_distance=flat_metric,
                neighbor_separation=flat_metric,
            ),
            "standard": CategoryLayoutDistributions(
                center_distance=flat_metric,
                neighbor_separation=flat_metric,
            ),
        },
        source={},
    )
    definite = HomeworldCandidateRecord(
        planet_id=pin_planet.id,
        perspective=1,
        confidence_tier=CONFIDENCE_DEFINITE,
    )
    low_row = HomeworldCandidateRecord(
        planet_id=low_id.id,
        perspective=None,
        confidence_tier=CONFIDENCE_POSSIBLE,
    )
    high_row = HomeworldCandidateRecord(
        planet_id=high_id.id,
        perspective=None,
        confidence_tier=CONFIDENCE_POSSIBLE,
    )
    view = _view(definite, low_row, high_row)
    annotated = apply_layout_prior_most_probable(
        (definite, low_row, high_row),
        turn=turn,
        view=view,
        player_count=player_count,
        layout_asset=flat_asset,
        map_center=center,
    )
    by_id = {row.planet_id: row for row in annotated}
    assert by_id[low_id.id].is_most_probable is True
    assert by_id[high_id.id].is_most_probable is False
    # Golden parity: lex-smaller planet id wins flat-cost ties.
    assert {row.planet_id for row in annotated if row.is_most_probable} == {low_id.id}


def test_layout_prior_caps_choices_per_sector(template_planet, sample_turn) -> None:
    """Dense possibles must not explode the joint product (map hang regression)."""
    from api.analytics.homeworld_locator.layout_prior import (
        MAX_LAYOUT_PRIOR_CHOICES_PER_SECTOR,
        build_sector_layout_states,
    )
    from api.analytics.homeworld_locator.layout_prior_enumerate import (
        EnumeratingLayoutPriorSolver,
        nearest_mid_choice_ids,
    )
    from api.analytics.homeworld_locator.layout_prior_problem import LayoutPriorProblem
    from api.analytics.homeworld_locator.layout_prior_stop_gate import NeverStopGate

    turn, pin = _eligible_turn(sample_turn, template_planet)
    center = (2000.0, 2000.0)
    player_count = 11
    radius = 550
    pin_angle = 0.0
    width = 2.0 * math.pi / player_count
    # Pack many possibles into one non-pin sector.
    sector_index = 3
    mid = pin_angle + sector_index * width
    planets = [
        _planet(
            template_planet,
            planet_id=1,
            x=int(center[0] + radius * math.cos(pin_angle)),
            y=int(center[1] + radius * math.sin(pin_angle)),
            ownerid=1,
        )
    ]
    candidates = [
        HomeworldCandidateRecord(
            planet_id=1,
            perspective=1,
            confidence_tier=CONFIDENCE_DEFINITE,
        )
    ]
    for offset in range(8):
        planet_id = 100 + offset
        angle = mid + (offset - 3.5) * (width / 20.0)
        planets.append(
            _planet(
                template_planet,
                planet_id=planet_id,
                x=int(center[0] + radius * math.cos(angle)),
                y=int(center[1] + radius * math.sin(angle)),
            )
        )
        candidates.append(
            HomeworldCandidateRecord(
                planet_id=planet_id,
                perspective=None,
                confidence_tier=CONFIDENCE_POSSIBLE,
            )
        )
    turn = replace(turn, planets=planets)
    view = HomeworldCandidateView(
        candidates=tuple(candidates),
        baseline_turn=1,
        baseline_degraded=False,
        available=True,
    )
    asset = _stub_layout_asset()
    r_inner, r_outer = asset.center_distance_band("standard")
    half = math.pi / player_count
    planets_by_id = {planet.id: planet for planet in planets}
    states = build_sector_layout_states(
        candidates=tuple(candidates),
        planets_by_id=planets_by_id,
        pin=planets[0],
        pin_angle=pin_angle,
        player_count=player_count,
        center=center,
        r_inner=r_inner,
        r_outer=r_outer,
        half=half,
        width=width,
        scan_origins=(),
        nebulas=(),
    )
    choice = next(state for state in states if state.kind == "choice")
    # Problem keeps the full legal set; enumerator alone applies the hard cap.
    assert len(choice.choice_planet_ids) == 8
    problem = LayoutPriorProblem(
        sector_states=states,
        planets_by_id=planets_by_id,
        center=center,
        r_inner=r_inner,
        r_outer=r_outer,
        distributions=asset.for_category("standard"),
    )
    assert len(nearest_mid_choice_ids(choice, problem)) == MAX_LAYOUT_PRIOR_CHOICES_PER_SECTOR
    solution = EnumeratingLayoutPriorSolver().solve(problem, stop_gate=NeverStopGate()).solution
    assert len(solution.chosen_planet_ids_by_sector) == 1
    assert next(iter(solution.chosen_planet_ids_by_sector.values())) in choice.choice_planet_ids
    # Selection still completes and marks one most-probable in the legal set.
    annotated = apply_layout_prior_most_probable(
        tuple(candidates),
        turn=turn,
        view=view,
        player_count=player_count,
        layout_asset=asset,
        map_center=center,
        solver=EnumeratingLayoutPriorSolver(),
    )
    most_probable = {row.planet_id for row in annotated if row.is_most_probable}
    assert len(most_probable) == 1
    assert most_probable.issubset(set(choice.choice_planet_ids))


def test_layout_prior_solver_injection_honors_fixed_choice(template_planet, sample_turn) -> None:
    """Injectable LayoutPriorSolver proves annotate path is solver-replaceable."""
    from api.analytics.homeworld_locator.layout_prior_report import (
        LayoutPriorSearchStats,
        LayoutPriorStopGateInfo,
        LayoutPriorTimingMs,
        build_run_report,
        problem_size_hints,
    )
    from api.analytics.homeworld_locator.layout_prior_solver import (
        LAYOUT_PRIOR_SOLVER_ENUMERATE,
        LayoutPriorSolution,
        LayoutPriorSolveResult,
    )

    turn, pin = _eligible_turn(sample_turn, template_planet)
    center = (2000.0, 2000.0)
    radius = 550
    player_count = 11
    pin_angle = 0.0
    sector_angle = pin_angle + (2.0 * math.pi / player_count)
    other_angle = pin_angle + 2.0 * (2.0 * math.pi / player_count)
    pin_planet = _planet(
        template_planet,
        planet_id=1,
        x=int(center[0] + radius * math.cos(pin_angle)),
        y=int(center[1] + radius * math.sin(pin_angle)),
        ownerid=1,
    )
    preferred = _planet(
        template_planet,
        planet_id=20,
        x=int(center[0] + radius * math.cos(sector_angle)),
        y=int(center[1] + radius * math.sin(sector_angle)),
    )
    ignored = _planet(
        template_planet,
        planet_id=21,
        x=int(center[0] + (radius + 20) * math.cos(sector_angle)),
        y=int(center[1] + (radius + 20) * math.sin(sector_angle)),
    )
    other_sector = _planet(
        template_planet,
        planet_id=30,
        x=int(center[0] + radius * math.cos(other_angle)),
        y=int(center[1] + radius * math.sin(other_angle)),
    )
    turn = replace(turn, planets=[pin_planet, preferred, ignored, other_sector])
    definite = HomeworldCandidateRecord(
        planet_id=pin_planet.id,
        perspective=1,
        confidence_tier=CONFIDENCE_DEFINITE,
    )
    preferred_row = HomeworldCandidateRecord(
        planet_id=preferred.id,
        perspective=None,
        confidence_tier=CONFIDENCE_POSSIBLE,
    )
    ignored_row = HomeworldCandidateRecord(
        planet_id=ignored.id,
        perspective=None,
        confidence_tier=CONFIDENCE_POSSIBLE,
    )
    other_row = HomeworldCandidateRecord(
        planet_id=other_sector.id,
        perspective=None,
        confidence_tier=CONFIDENCE_POSSIBLE,
    )
    view = _view(definite, preferred_row, ignored_row, other_row)

    class _FixedSolver:
        def solve(self, problem, *, stop_gate):
            del stop_gate
            choice_sectors = [s for s in problem.sector_states if s.kind == "choice"]
            assert choice_sectors
            # Force a specific planet regardless of cost ranking.
            chosen = {choice_sectors[0].sector_index: preferred.id}
            solution = LayoutPriorSolution(
                chosen_planet_ids_by_sector=chosen,
                stand_in_positions_by_sector={},
                cost=0.0,
                tie_key=tuple(sorted(chosen.items())),
            )
            report = build_run_report(
                game_id=problem.seed_game_id,
                turn=problem.seed_turn,
                perspective=problem.seed_perspective,
                solver=LAYOUT_PRIOR_SOLVER_ENUMERATE,
                stop_gate=LayoutPriorStopGateInfo(kind="never"),
                stop_reason="exhausted",
                timing=LayoutPriorTimingMs(greedy_ms=0.0, sa_ms=0.0, refine_ms=0.0, total_ms=0.0),
                search=LayoutPriorSearchStats(
                    sa_steps_attempted=0,
                    sa_steps_accepted=0,
                    greedy_cost=0.0,
                    pre_refine_cost=0.0,
                    final_cost=0.0,
                    tie_key=solution.tie_key,
                ),
                problem_size=problem_size_hints(
                    choice_sector_count=len(choice_sectors),
                    total_possibles=len(choice_sectors),
                    stand_in_sector_count=0,
                    planet_count=len(problem.planets_by_id),
                    category=problem.layout_category,
                ),
                incumbent_cost_series=(),
            )
            return LayoutPriorSolveResult(solution=solution, report=report)

    annotated = apply_layout_prior_most_probable(
        (definite, preferred_row, ignored_row, other_row),
        turn=turn,
        view=view,
        player_count=player_count,
        layout_asset=_stub_layout_asset(),
        map_center=center,
        solver=_FixedSolver(),
    )
    by_id = {row.planet_id: row for row in annotated}
    assert by_id[preferred.id].is_most_probable is True
    assert by_id[ignored.id].is_most_probable is False
    assert by_id[other_sector.id].is_most_probable is False
    assert by_id[pin_planet.id].is_most_probable is False
    assert {row.planet_id for row in annotated if row.is_most_probable} == {preferred.id}


def test_empty_nebular_sector_stand_in_does_not_block_most_probable(
    template_planet, sample_turn, persistence
) -> None:
    """680224-style: one orphan sector, another sector empty but scan-incomplete."""
    from tests.test_homeworld_location_evidence import _ship

    turn, _pin = _eligible_turn(sample_turn, template_planet)
    center = (2000.0, 2000.0)
    player_count = 11
    radius = 550
    pin_angle = 0.0
    orphan_angle = 5.0 * 2.0 * math.pi / player_count
    pin_planet = _planet(
        template_planet,
        planet_id=1,
        x=int(center[0] + radius * math.cos(pin_angle)),
        y=int(center[1] + radius * math.sin(pin_angle)),
        ownerid=1,
    )
    orphan = _planet(
        template_planet,
        planet_id=2,
        x=int(center[0] + radius * math.cos(orphan_angle)),
        y=int(center[1] + radius * math.sin(orphan_angle)),
    )
    ship = _ship(
        turn.ships[0] if turn.ships else sample_turn.ships[0],
        ship_id=99,
        x=pin_planet.x,
        y=pin_planet.y,
        ownerid=turn.player.id,
    )
    turn = replace(
        turn,
        settings=replace(turn.settings, planetscanrange=80),
        planets=[pin_planet, orphan],
        ships=[ship],
    )
    services = core_services(persistence, {1: turn})
    persistence.put_baseline(
        628580,
        1,
        HomeworldLocatorGameState(
            candidates=(
                HomeworldCandidateRecord(
                    planet_id=pin_planet.id,
                    perspective=1,
                    confidence_tier=CONFIDENCE_DEFINITE,
                ),
                HomeworldCandidateRecord(
                    planet_id=orphan.id,
                    perspective=None,
                    confidence_tier=CONFIDENCE_POSSIBLE,
                ),
            ),
            baseline_turn=1,
            baseline_degraded=False,
            settings_fingerprint=homeworld_settings_fingerprint(turn.settings),
        ),
        HomeworldEvidenceAggregate(turn=1, baseline_turn=1),
    )

    ctx = _materialize_ctx(services, turn, {1: turn})
    view = materialize_homeworld_candidate_view(ctx, shell_turn=turn)
    by_id = {row.planet_id: row for row in view.candidates}
    assert by_id[pin_planet.id].is_most_probable is False
    assert by_id[orphan.id].is_most_probable is True

    payload = get_homeworld_locator(
        turn,
        load_turn=lambda n: {1: turn}.get(n),
        export_services={ANALYTIC_ID: services},
    )
    orphan_row = next(row for row in payload["rows"] if row["planetId"] == orphan.id)
    assert orphan_row["isMostProbable"] is True
    assert all(
        marker["isMostProbable"] == row["isMostProbable"]
        for marker, row in zip(payload["markers"], payload["rows"], strict=True)
    )
    # Stand-in is internal only: no extra candidates or markers.
    assert len(payload["markers"]) == 2


def test_layout_prior_selection_round_trips_on_evidence_aggregate() -> None:
    from api.analytics.homeworld_locator.constants import LAYOUT_PRIOR_ALGORITHM_VERSION
    from api.analytics.homeworld_locator.serialization import (
        homeworld_evidence_aggregate_from_json,
        homeworld_evidence_aggregate_to_json,
    )

    fingerprint = ((12, CONFIDENCE_DEFINITE, 1), (34, CONFIDENCE_POSSIBLE, None))
    observations = (
        OriginDistanceObservation(turn=12, x=100, y=200, matched_planet_ids=(12, 34)),
        OriginDistanceObservation(turn=13, x=300, y=400, matched_planet_ids=(12,)),
    )
    aggregate = HomeworldEvidenceAggregate(
        turn=13,
        baseline_turn=1,
        origin_distance_observations=observations,
        layout_prior_algorithm_version=LAYOUT_PRIOR_ALGORITHM_VERSION,
        layout_prior_input_fingerprint=fingerprint,
        most_probable_planet_ids=(12, 34),
    )
    wire = homeworld_evidence_aggregate_to_json(aggregate)
    assert wire["originDistanceObservations"] == [
        {"turn": 12, "x": 100, "y": 200, "matchedPlanetIds": [12, 34]},
        {"turn": 13, "x": 300, "y": 400, "matchedPlanetIds": [12]},
    ]
    assert "evidenceHits" not in wire
    assert wire["layoutPriorSelection"] == {
        "algorithmVersion": LAYOUT_PRIOR_ALGORITHM_VERSION,
        "inputFingerprint": [
            {"planetId": 12, "confidenceTier": CONFIDENCE_DEFINITE, "perspective": 1},
            {"planetId": 34, "confidenceTier": CONFIDENCE_POSSIBLE, "perspective": None},
        ],
        "mostProbablePlanetIds": [12, 34],
    }
    assert "promotionThreshold" not in wire["layoutPriorSelection"]
    restored = homeworld_evidence_aggregate_from_json(wire)
    assert restored.origin_distance_observations == observations
    assert restored.layout_prior_algorithm_version == LAYOUT_PRIOR_ALGORITHM_VERSION
    assert restored.layout_prior_promotion_threshold is None
    assert restored.layout_prior_input_fingerprint == fingerprint
    assert restored.most_probable_planet_ids == (12, 34)
    # Legacy evidenceHits-only payloads load with empty observations (re-refine expected).
    legacy_hits_only = homeworld_evidence_aggregate_from_json(
        {
            "turn": 13,
            "baselineTurn": 1,
            "evidenceHits": [{"planetId": 12, "turn": 12, "kind": "origin_distance"}],
            "singleStarbasePromotions": [],
        }
    )
    assert legacy_hits_only.origin_distance_observations == ()
    # Legacy wire that still carries promotionThreshold remains readable.
    legacy_with_threshold = homeworld_evidence_aggregate_from_json(
        {
            "turn": 13,
            "baselineTurn": 1,
            "originDistanceObservations": [],
            "singleStarbasePromotions": [],
            "layoutPriorSelection": {
                "algorithmVersion": LAYOUT_PRIOR_ALGORITHM_VERSION,
                "promotionThreshold": 2,
                "inputFingerprint": [
                    {"planetId": 12, "confidenceTier": CONFIDENCE_DEFINITE, "perspective": 1},
                ],
                "mostProbablePlanetIds": [12],
            },
        }
    )
    assert legacy_with_threshold.layout_prior_algorithm_version == LAYOUT_PRIOR_ALGORITHM_VERSION
    assert legacy_with_threshold.layout_prior_promotion_threshold == 2
    assert legacy_with_threshold.most_probable_planet_ids == (12,)
    assert "layoutPriorSelection" not in homeworld_evidence_aggregate_to_json(
        HomeworldEvidenceAggregate(turn=1, baseline_turn=1)
    )
    # Legacy selection without inputFingerprint is dropped (forces recompute).
    legacy = homeworld_evidence_aggregate_from_json(
        {
            "turn": 13,
            "baselineTurn": 1,
            "originDistanceObservations": [],
            "singleStarbasePromotions": [],
            "layoutPriorSelection": {
                "algorithmVersion": LAYOUT_PRIOR_ALGORITHM_VERSION,
                "mostProbablePlanetIds": [12],
            },
        }
    )
    assert legacy.layout_prior_algorithm_version is None
    assert legacy.most_probable_planet_ids == ()


def test_shell_layout_prior_persisted_and_reused(
    template_planet, sample_turn, persistence, monkeypatch
) -> None:
    """First shell materialize persists selection; second call reuses without recomputing."""
    from api.analytics.homeworld_locator import baseline_ensure as baseline_mod
    from api.analytics.homeworld_locator.constants import LAYOUT_PRIOR_ALGORITHM_VERSION
    from api.analytics.homeworld_locator.layout_prior import layout_prior_input_fingerprint
    from api.config import get_config, set_config

    turn, _pin = _eligible_turn(sample_turn, template_planet)
    center = (2000.0, 2000.0)
    player_count = 11
    radius = 550
    pin_angle = 0.0
    orphan_angle = 5.0 * 2.0 * math.pi / player_count
    pin_planet = _planet(
        template_planet,
        planet_id=1,
        x=int(center[0] + radius * math.cos(pin_angle)),
        y=int(center[1] + radius * math.sin(pin_angle)),
        ownerid=1,
    )
    orphan = _planet(
        template_planet,
        planet_id=2,
        x=int(center[0] + radius * math.cos(orphan_angle)),
        y=int(center[1] + radius * math.sin(orphan_angle)),
    )
    turn = replace(turn, planets=[pin_planet, orphan], ships=())
    services = core_services(persistence, {1: turn})
    persistence.put_baseline(
        628580,
        1,
        HomeworldLocatorGameState(
            candidates=(
                HomeworldCandidateRecord(
                    planet_id=pin_planet.id,
                    perspective=1,
                    confidence_tier=CONFIDENCE_DEFINITE,
                ),
                HomeworldCandidateRecord(
                    planet_id=orphan.id,
                    perspective=None,
                    confidence_tier=CONFIDENCE_POSSIBLE,
                ),
            ),
            baseline_turn=1,
            baseline_degraded=False,
            settings_fingerprint=homeworld_settings_fingerprint(turn.settings),
        ),
        HomeworldEvidenceAggregate(turn=1, baseline_turn=1),
    )

    calls = {"n": 0}
    real = baseline_mod.apply_layout_prior_most_probable

    def counting_apply(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(baseline_mod, "apply_layout_prior_most_probable", counting_apply)

    ctx = _materialize_ctx(services, turn, {1: turn})
    first = materialize_homeworld_candidate_view(ctx, shell_turn=turn)
    stored = persistence.get_evidence_aggregate(628580, 1, turn.settings.turn)
    assert stored is not None
    assert stored.layout_prior_algorithm_version == LAYOUT_PRIOR_ALGORITHM_VERSION
    assert stored.layout_prior_promotion_threshold is None
    assert stored.layout_prior_input_fingerprint == layout_prior_input_fingerprint(first.candidates)
    assert orphan.id in stored.most_probable_planet_ids
    assert calls["n"] == 1

    second = materialize_homeworld_candidate_view(ctx, shell_turn=turn)
    assert calls["n"] == 1
    assert {row.planet_id for row in first.candidates if row.is_most_probable} == {
        row.planet_id for row in second.candidates if row.is_most_probable
    }

    # Stale algorithm version forces recompute + rewrite.
    persistence.put_evidence_aggregate(
        628580,
        1,
        replace(
            stored,
            layout_prior_algorithm_version=LAYOUT_PRIOR_ALGORITHM_VERSION - 1
            if LAYOUT_PRIOR_ALGORITHM_VERSION > 1
            else 999,
            most_probable_planet_ids=(pin_planet.id,),
        ),
    )
    third = materialize_homeworld_candidate_view(ctx, shell_turn=turn)
    assert calls["n"] == 2
    assert {row.planet_id for row in third.candidates if row.is_most_probable} == {
        row.planet_id for row in first.candidates if row.is_most_probable
    }
    rewritten = persistence.get_evidence_aggregate(628580, 1, turn.settings.turn)
    assert rewritten is not None
    assert rewritten.layout_prior_algorithm_version == LAYOUT_PRIOR_ALGORITHM_VERSION
    assert orphan.id in rewritten.most_probable_planet_ids
    assert pin_planet.id not in rewritten.most_probable_planet_ids

    # Soft-evidence λ config change alone does not force recompute (reuse keys
    # are algorithm version + input fingerprint; clear persistence when retuning λ).
    prior_calls = calls["n"]
    cfg = get_config()
    set_config(
        replace(
            cfg,
            homeworld_locator=replace(
                cfg.homeworld_locator,
                origin_distance_evidence_lambda=0.5,
            ),
        )
    )
    try:
        fourth = materialize_homeworld_candidate_view(ctx, shell_turn=turn)
        assert calls["n"] == prior_calls
        after_lambda = persistence.get_evidence_aggregate(628580, 1, turn.settings.turn)
        assert after_lambda is not None
        assert after_lambda.layout_prior_promotion_threshold is None
        assert {row.planet_id for row in fourth.candidates if row.is_most_probable} == {
            row.planet_id for row in first.candidates if row.is_most_probable
        }
    finally:
        set_config(cfg)

    # Fingerprint mismatch (post-cull candidate set) forces recompute.
    prior_calls = calls["n"]
    persistence.put_evidence_aggregate(
        628580,
        1,
        replace(
            rewritten,
            layout_prior_input_fingerprint=((pin_planet.id, CONFIDENCE_DEFINITE, 1),),
            most_probable_planet_ids=(pin_planet.id,),
        ),
    )
    fifth = materialize_homeworld_candidate_view(ctx, shell_turn=turn)
    assert calls["n"] == prior_calls + 1
    assert {row.planet_id for row in fifth.candidates if row.is_most_probable} == {
        row.planet_id for row in first.candidates if row.is_most_probable
    }
    after_fingerprint = persistence.get_evidence_aggregate(628580, 1, turn.settings.turn)
    assert after_fingerprint is not None
    assert after_fingerprint.layout_prior_input_fingerprint == layout_prior_input_fingerprint(
        fifth.candidates
    )
    assert orphan.id in after_fingerprint.most_probable_planet_ids
