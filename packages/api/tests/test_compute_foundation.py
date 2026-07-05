"""Tests for compute orchestrator foundation types and registry validation."""

from __future__ import annotations

import pytest
from api.analytics.catalog import TurnAnalyticCatalogEntry
from api.analytics.export_types import ExportScope
from api.analytics.exports.empty import empty_export_catalog_for
from api.analytics.registration import TurnAnalyticRegistration
from api.compute import (
    WILDCARD,
    AnalyticComputeProfile,
    ComputeScope,
    ComputeStepSpec,
    ScopeKeySpec,
    build_compute_registry,
    fingerprint_parameters,
    normalize_export_scope_to_compute_scope,
    validate_turn_analytic_compute_registration,
)


class _StubPersistencePolicy:
    def is_satisfied(self, _ctx, _scope) -> bool:
        return False

    def persist(self, _ctx, _scope, _result_wire) -> None:
        return None

    def invalidate(self, _ctx, _scope) -> None:
        return None


def _catalog_entry(analytic_id: str = "test-analytic") -> TurnAnalyticCatalogEntry:
    return TurnAnalyticCatalogEntry(
        id=analytic_id,
        name="Test",
        supports_table=True,
        supports_map=False,
        type="selectable",
    )


def _compute_registration(**kwargs) -> TurnAnalyticRegistration:
    analytic_id = kwargs.get("analytic_id", "test-analytic")
    scope_key_spec = kwargs.get(
        "scope_key_spec",
        ScopeKeySpec(axes=("perspective", "turn", "player_id")),
    )
    compute_profile = kwargs.get(
        "compute_profile",
        AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind="materialize", backend="thread"),),
        ),
    )
    persistence_policy = kwargs.get("persistence_policy", _StubPersistencePolicy())
    build_step_job_wires = kwargs.get(
        "build_step_job_wires",
        (("materialize", lambda **_kwargs: {"job": True}),),
    )
    run_steps = kwargs.get(
        "run_steps",
        (("materialize", lambda _job: {"result": True}),),
    )

    def compute(_ctx) -> dict:
        return {"analyticId": analytic_id}

    return TurnAnalyticRegistration(
        catalog_entry=_catalog_entry(analytic_id),
        compute=compute,
        export_catalog=empty_export_catalog_for(analytic_id),
        scope_key_spec=scope_key_spec,
        compute_profile=compute_profile,
        persistence_policy=persistence_policy,
        build_step_job_wires=build_step_job_wires,
        run_steps=run_steps,
    )


def test_normalize_export_scope_maps_declared_axes_and_wildcards_others():
    export_scope = ExportScope(game_id=628580, perspective=1, turn=8, player_id=3)
    scores_spec = ScopeKeySpec(axes=("perspective", "turn", "player_id"))
    scope = normalize_export_scope_to_compute_scope(
        export_scope,
        analytic_id="scores",
        scope_key_spec=scores_spec,
    )
    assert scope == ComputeScope(
        analytic_id="scores",
        game_id=628580,
        perspective=1,
        turn=8,
        player_id=3,
        parameters=(),
    )

    connections_spec = ScopeKeySpec(axes=("perspective", "turn"))
    connections_scope = normalize_export_scope_to_compute_scope(
        export_scope,
        analytic_id="connections",
        scope_key_spec=connections_spec,
    )
    assert connections_scope.player_id == WILDCARD
    assert connections_scope.perspective == 1
    assert connections_scope.turn == 8


def test_normalize_export_scope_requires_player_id_when_axis_declared():
    export_scope = ExportScope(game_id=1, perspective=1, turn=2, player_id=None)
    with pytest.raises(ValueError, match="player_id is required"):
        normalize_export_scope_to_compute_scope(
            export_scope,
            analytic_id="scores",
            scope_key_spec=ScopeKeySpec(axes=("perspective", "turn", "player_id")),
        )


def test_fingerprint_parameters_sorts_and_stringifies():
    spec = ScopeKeySpec(
        axes=("perspective", "turn"),
        parameter_fields=("warp_speed", "flare_mode"),
    )
    export_scope = ExportScope(game_id=1, perspective=2, turn=3)
    scope = normalize_export_scope_to_compute_scope(
        export_scope,
        analytic_id="connections",
        scope_key_spec=spec,
        parameters={"flare_mode": "only", "warp_speed": 9, "ignored": "x"},
    )
    assert scope.parameters == (("flare_mode", "only"), ("warp_speed", "9"))


def test_fingerprint_parameters_fills_missing_fields():
    assert fingerprint_parameters(
        {"warp_speed": 7},
        parameter_fields=("flare_mode", "warp_speed"),
    ) == (("flare_mode", ""), ("warp_speed", "7"))


def test_validate_compute_registration_accepts_complete_profile():
    registration = _compute_registration()
    compute_registration = validate_turn_analytic_compute_registration(registration)
    assert compute_registration is not None
    assert compute_registration.analytic_id == "test-analytic"
    assert "materialize" in compute_registration.build_step_job_wire
    assert "materialize" in compute_registration.run_step


def test_validate_compute_registration_skips_when_profile_absent():
    registration = TurnAnalyticRegistration(
        catalog_entry=_catalog_entry(),
        compute=lambda _ctx: {"analyticId": "test-analytic"},
        export_catalog=empty_export_catalog_for("test-analytic"),
    )
    assert validate_turn_analytic_compute_registration(registration) is None


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"scope_key_spec": None}, "scope_key_spec"),
        ({"persistence_policy": None}, "persistence_policy"),
        (
            {
                "compute_profile": AnalyticComputeProfile(steps=()),
            },
            "steps must not be empty",
        ),
        (
            {
                "compute_profile": AnalyticComputeProfile(
                    steps=(ComputeStepSpec(step_kind="a", backend="thread"),) * 2,
                ),
            },
            "duplicate compute step_kind",
        ),
        (
            {
                "compute_profile": AnalyticComputeProfile(
                    steps=(ComputeStepSpec(step_kind="materialize", backend="unknown"),),
                ),
            },
            "unknown backend",
        ),
        (
            {
                "build_step_job_wires": (),
            },
            "missing build_step_job_wire",
        ),
        (
            {
                "run_steps": (),
            },
            "missing run_step",
        ),
        (
            {
                "build_step_job_wires": (
                    ("materialize", lambda **_kwargs: {}),
                    ("extra", lambda **_kwargs: {}),
                ),
            },
            "unknown build_step_job_wire",
        ),
        (
            {
                "run_steps": (
                    ("materialize", lambda _job: {}),
                    ("extra", lambda _job: {}),
                ),
            },
            "unknown run_step",
        ),
        (
            {
                "scope_key_spec": ScopeKeySpec(axes=(), parameter_fields=()),
            },
            "must declare at least one axis",
        ),
    ],
)
def test_validate_compute_registration_rejects_invalid_profiles(overrides, match):
    registration = _compute_registration(**overrides)
    with pytest.raises(RuntimeError, match=match):
        validate_turn_analytic_compute_registration(registration)


def test_build_compute_registry_rejects_duplicate_compute_ids():
    registrations = (
        _compute_registration(analytic_id="dup"),
        _compute_registration(analytic_id="dup"),
    )
    with pytest.raises(RuntimeError, match="Duplicate compute registration"):
        build_compute_registry(registrations)


def test_production_compute_registry_imports_without_profiles():
    from api.compute.registry import COMPUTE_REGISTRY

    assert COMPUTE_REGISTRY == {}
