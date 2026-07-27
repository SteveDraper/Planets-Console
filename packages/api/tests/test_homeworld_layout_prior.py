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
from api.analytics.homeworld_locator.models import CONFIDENCE_DEFINITE, CONFIDENCE_POSSIBLE
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
    percentiles = tuple(
        support_min + (support_max - support_min) * index / 100 for index in range(101)
    )
    return SmoothedMetricDistribution(
        sample_count=100,
        support_min=support_min,
        support_max=support_max,
        percentiles=percentiles,
    )


def _stub_layout_asset(*, support_min: float = 500.0, support_max: float = 600.0):
    metric = _linear_metric(support_min=support_min, support_max=support_max)
    category = CategoryLayoutDistributions(
        center_distance=metric,
        neighbor_separation=metric,
    )
    return LayoutDistributionsAsset(
        schema_version=1,
        bin_width_ly=10.0,
        smoothing_method="laplace",
        laplace_alpha=1.0,
        percentile_step=1,
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


def _view(*candidates: HomeworldCandidateRecord) -> HomeworldCandidateView:
    return HomeworldCandidateView(
        candidates=candidates,
        baseline_turn=1,
        baseline_degraded=False,
        available=True,
    )


def test_percentile_for_value_inverts_value_at_percentile() -> None:
    metric = _linear_metric(support_min=100.0, support_max=200.0)
    assert metric.percentile_for_value(100.0) == pytest.approx(0.0)
    assert metric.percentile_for_value(150.0) == pytest.approx(50.0)
    assert metric.percentile_for_value(200.0) == pytest.approx(100.0)
    assert metric.value_at_percentile(metric.percentile_for_value(137.5)) == pytest.approx(137.5)


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
        percentiles=(500.0,) * 101,
    )
    flat_asset = LayoutDistributionsAsset(
        schema_version=1,
        bin_width_ly=10.0,
        smoothing_method="laplace",
        laplace_alpha=1.0,
        percentile_step=1,
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


def test_layout_prior_caps_choices_per_sector(template_planet, sample_turn) -> None:
    """Dense possibles must not explode the joint product (map hang regression)."""
    from api.analytics.homeworld_locator.layout_prior import (
        MAX_LAYOUT_PRIOR_CHOICES_PER_SECTOR,
        _build_sector_states,
    )

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
    states = _build_sector_states(
        candidates=tuple(candidates),
        planets_by_id={planet.id: planet for planet in planets},
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
    assert len(choice.choice_planet_ids) == MAX_LAYOUT_PRIOR_CHOICES_PER_SECTOR
    # Selection still completes and marks one most-probable.
    annotated = apply_layout_prior_most_probable(
        tuple(candidates),
        turn=turn,
        view=view,
        player_count=player_count,
        layout_asset=asset,
        map_center=center,
    )
    assert sum(1 for row in annotated if row.is_most_probable) == 1


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
    services = core_services(persistence, {1: turn, 5: turn})
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

    view = materialize_homeworld_candidate_view(services, shell_turn=turn)
    by_id = {row.planet_id: row for row in view.candidates}
    assert by_id[pin_planet.id].is_most_probable is False
    assert by_id[orphan.id].is_most_probable is True

    payload = get_homeworld_locator(
        turn,
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

    aggregate = HomeworldEvidenceAggregate(
        turn=13,
        baseline_turn=1,
        layout_prior_algorithm_version=LAYOUT_PRIOR_ALGORITHM_VERSION,
        most_probable_planet_ids=(12, 34),
    )
    wire = homeworld_evidence_aggregate_to_json(aggregate)
    assert wire["layoutPriorSelection"] == {
        "algorithmVersion": LAYOUT_PRIOR_ALGORITHM_VERSION,
        "mostProbablePlanetIds": [12, 34],
    }
    restored = homeworld_evidence_aggregate_from_json(wire)
    assert restored.layout_prior_algorithm_version == LAYOUT_PRIOR_ALGORITHM_VERSION
    assert restored.most_probable_planet_ids == (12, 34)
    assert "layoutPriorSelection" not in homeworld_evidence_aggregate_to_json(
        HomeworldEvidenceAggregate(turn=1, baseline_turn=1)
    )


def test_shell_layout_prior_persisted_and_reused(
    template_planet, sample_turn, persistence, monkeypatch
) -> None:
    """First shell materialize persists selection; second call reuses without recomputing."""
    from api.analytics.homeworld_locator import baseline_ensure as baseline_mod
    from api.analytics.homeworld_locator.constants import LAYOUT_PRIOR_ALGORITHM_VERSION

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
    services = core_services(persistence, {1: turn, 5: turn})
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

    first = materialize_homeworld_candidate_view(services, shell_turn=turn)
    stored = persistence.get_evidence_aggregate(628580, 1, turn.settings.turn)
    assert stored is not None
    assert stored.layout_prior_algorithm_version == LAYOUT_PRIOR_ALGORITHM_VERSION
    assert orphan.id in stored.most_probable_planet_ids
    assert calls["n"] == 1

    second = materialize_homeworld_candidate_view(services, shell_turn=turn)
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
    third = materialize_homeworld_candidate_view(services, shell_turn=turn)
    assert calls["n"] == 2
    assert {row.planet_id for row in third.candidates if row.is_most_probable} == {
        row.planet_id for row in first.candidates if row.is_most_probable
    }
    rewritten = persistence.get_evidence_aggregate(628580, 1, turn.settings.turn)
    assert rewritten is not None
    assert rewritten.layout_prior_algorithm_version == LAYOUT_PRIOR_ALGORITHM_VERSION
    assert orphan.id in rewritten.most_probable_planet_ids
    assert pin_planet.id not in rewritten.most_probable_planet_ids
