"""Isolated reproduction of the slowest scores tier in local/diagnostics.json.

Fingerprint from the 2026-10-15 game 686674 / perspective 21 / shell turn 16
compute snapshot: ``scores@g686674@p21@t10@pl46`` ``tier_solve`` step 4
``admit_ship_torpedoes`` took 95.96 s on the thread pool while 8 workers were
busy. An idle run of that same step is shorter. Partial slot fills admit an
empty or full launcher bank, and beam counts of empty, one, one short of full,
and full. That catalog is about 38k combos, and the tier fills its solution
cap before the 1.0 deterministic-time budget. Catalog score indexes are built
once per catalog.

Opt-in. Each case reads the local file store and runs several CP-SAT tiers.
Default ``make test`` skips them. Select one with ``-k``.

    SCORES_OUTLIER_REPRO=1 uv run pytest \\
        tests/test_scores_admit_ship_outlier_repro.py -s
"""

from __future__ import annotations

import os
import time
from collections import Counter
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from api.analytics.export_types import ExportScope
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.serialization import (
    fleet_evidence_mark_from_json,
    fleet_ledger_is_ensure_final,
    persisted_fleet_ledger_from_json,
)
from api.analytics.fleet.types import FleetEvidenceMark, FleetTurnSnapshot
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_admission import (
    resolve_inference_admission_skip,
)
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    PriorTurnFleetTorpResolution,
    records_for_scope,
    resolution_from_fleet_records,
)
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.scores.compute_orchestration import (
    _apply_fleet_resolution_to_row_run,
    run_scores_tier_solve,
)
from api.analytics.scores.tier_row_run_registry import reset_tier_row_run_registry_for_tests
from api.analytics.scores.tier_solve_jobs import _load_turn
from api.config import get_config, set_config
from api.errors import NotFoundError
from api.models.game import TurnInfo
from api.storage.base import StorageBackend
from api.storage_factory import clear_backend_cache
from ortools.sat.python import cp_model

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STORAGE_ROOT = REPO_ROOT / ".data"

GAME_ID = 686674
PERSPECTIVE = 21
TURN = 10
PLAYER_ID = 46
OUTLIER_TIER_INDEX = 4
OUTLIER_TIER_ID = "admit_ship_torpedoes"
# Orchestrator wall while 8 workers were busy.
DIAGNOSTIC_LOADED_WALL_SECONDS = 95.96
# Idle floor after partial slot counts are limited. The tier fills its
# solution cap before the 1.0 deterministic-time budget.
IDLE_MINIMUM_WALL_SECONDS = 5.0

# Early-sweep outlier from local/diagnostics_early.json. Loaded wall is the
# completed step while 8 workers were busy.
TURN3_PLAYER10_LOADED_WALL_SECONDS = 31.59

# Late-window outlier from local/diagnostics_late2.json. The row stopped on
# full_components. Loaded walls are the completed steps while 8 workers were busy.
TURN10_PLAYER51_ADMIT_LOADED_WALL_SECONDS = 30.81
TURN10_PLAYER51_THROUGH_TIER_INDEX = 6

# Largest modest_planet_defense step in local/diagnostics_late3.json.
TURN15_PLAYER38_MODEST_LOADED_WALL_SECONDS = 20.81
TURN15_PLAYER38_MODEST_TIER_INDEX = 5

# Empty-catalog acquired-warship admit from local/diagnostics_late5.json.
# Loaded wall is the persisted tier emission while 8 workers were busy.
TURN8_PLAYER9_ADMIT_LOADED_WALL_SECONDS = 125.88

# Longest admit_ship_torpedoes complete in local/diagnostics_late6.json.
# Worker execution time while 8 workers were busy, not queue wait.
TURN15_PLAYER28_ADMIT_LOADED_WALL_SECONDS = 13.38

# Median admit_ship_torpedoes emission in the late-8 persisted run.
# 530 steps, median 1.684s. This row is one of the two central observations:
# time-limited, ship-first prefix, 13,365 combos, one newly admitted solution.
TURN10_PLAYER4_ADMIT_LOADED_WALL_SECONDS = 1.684
TURN10_PLAYER4_ADMIT_COMBO_COUNT = 13_365

_active_tier: ContextVar[str] = ContextVar("outlier_repro_tier", default="")
_active_phase: ContextVar[str] = ContextVar("outlier_repro_phase", default="other")


@dataclass
class BuildSample:
    tier: str
    phase: str
    wall_seconds: float
    variables: int
    constraints: int
    combos: int


@dataclass
class SolveSample:
    tier: str
    phase: str
    wall_seconds: float
    deterministic_time: float
    status: str
    booleans: int
    conflicts: int
    branches: int


@dataclass
class SpanSample:
    tier: str
    name: str
    wall_seconds: float


@dataclass
class TierSample:
    index: int
    tier_id: str
    wall_seconds: float
    outcome: str
    combo_count: int
    stopped_reason: str
    solve_wall_seconds: float
    deterministic_time: float
    structural_hits: int


@dataclass
class OutlierReproduction:
    fleet_input_status: str
    record_count: int
    military_delta_2x: int = 0
    warship_delta: int = 0
    freighter_delta: int = 0
    starbases_owned: int = 0
    tiers: list[TierSample] = field(default_factory=list)
    builds: list[BuildSample] = field(default_factory=list)
    solves: list[SolveSample] = field(default_factory=list)
    spans: list[SpanSample] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    band_callbacks: int = 0
    band_callback_seconds: float = 0.0
    solution_action_ids: list[tuple[str, ...]] = field(default_factory=list)
    solution_families: list[str | None] = field(default_factory=list)

    def tier(self, index: int) -> TierSample | None:
        for sample in self.tiers:
            if sample.index == index:
                return sample
        return None


class _PhaseProbe:
    """Time model builds and ``CpSolver.solve`` without changing the search."""

    def __init__(self, report: OutlierReproduction) -> None:
        self._report = report
        self._installed = False
        self._original_solve = cp_model.CpSolver.solve
        self._solver_module = None
        self._original_build = None
        self._tier_step_module = None
        self._original_probe = None
        self._original_solve_problem = None
        self._original_catalog = None
        self._original_merge = None
        self._original_expand = None
        self._family_module = None
        self._original_step_leftover = None
        self._original_family_leftover = None
        self._original_non_torp = None

    def install(self) -> None:
        from api.analytics.military_score_inference import (
            actions,
            inference_api_payload,
            policy_ladder,
            policy_ladder_tier_step,
            ship_first_family,
            solver,
        )

        report = self._report
        original_solve = self._original_solve

        def timed_solve(solver, model, *args, **kwargs):
            started = time.perf_counter()
            status = original_solve(solver, model, *args, **kwargs)
            wall_seconds = time.perf_counter() - started
            try:
                deterministic_time = float(solver.deterministic_time)
            except RuntimeError, TypeError, ValueError:
                deterministic_time = 0.0
            try:
                status_name = solver.status_name(status)
            except RuntimeError, TypeError, ValueError:
                status_name = str(status)
            report.solves.append(
                SolveSample(
                    tier=_active_tier.get(),
                    phase=_active_phase.get(),
                    wall_seconds=wall_seconds,
                    deterministic_time=deterministic_time,
                    status=status_name,
                    booleans=_solver_int(solver, "num_booleans"),
                    conflicts=_solver_int(solver, "num_conflicts"),
                    branches=_solver_int(solver, "num_branches"),
                )
            )
            return status

        original_build = solver._build_model

        def timed_build(problem, merged_combo_catalog):
            started = time.perf_counter()
            built = original_build(problem, merged_combo_catalog)
            wall_seconds = time.perf_counter() - started
            proto = built.model.proto
            report.builds.append(
                BuildSample(
                    tier=_active_tier.get(),
                    phase=_active_phase.get(),
                    wall_seconds=wall_seconds,
                    variables=len(proto.variables),
                    constraints=len(proto.constraints),
                    combos=len(problem.ship_build_combos),
                )
            )
            return built

        original_probe = policy_ladder_tier_step.probe_degrade_aggregate_rewrites

        def timed_probe(*args, **kwargs):
            token = _active_phase.set("degrade")
            try:
                return original_probe(*args, **kwargs)
            finally:
                _active_phase.reset(token)

        original_solve_problem = policy_ladder_tier_step.solve_inference_problem

        def timed_solve_problem(*args, **kwargs):
            token = _active_phase.set("structural")
            started = time.perf_counter()
            try:
                return original_solve_problem(*args, **kwargs)
            finally:
                report.spans.append(
                    SpanSample(
                        tier=_active_tier.get(),
                        name="solve_problem",
                        wall_seconds=time.perf_counter() - started,
                    )
                )
                _active_phase.reset(token)

        def timed_span(name: str, fn):
            def wrapped(*args, **kwargs):
                started = time.perf_counter()
                try:
                    return fn(*args, **kwargs)
                finally:
                    report.spans.append(
                        SpanSample(
                            tier=_active_tier.get(),
                            name=name,
                            wall_seconds=time.perf_counter() - started,
                        )
                    )

            return wrapped

        original_catalog = policy_ladder_tier_step.build_action_catalog_from_turn

        def timed_catalog(*args, **kwargs):
            started = time.perf_counter()
            catalog = original_catalog(*args, **kwargs)
            report.spans.append(
                SpanSample(
                    tier=_active_tier.get(),
                    name="catalog",
                    wall_seconds=time.perf_counter() - started,
                )
            )
            actions = ", ".join(
                f"{action.id} score={action.score_delta_2x} ub={action.upper_bound}"
                for action in catalog.aggregate_actions
            )
            report.notes.append(
                f"{_active_tier.get()} combos={len(catalog.ship_build_combos)} "
                f"aggregates={len(catalog.aggregate_actions)} [{actions}]"
            )
            return catalog

        original_merge = solver.merge_score_equivalent_combos
        original_expand = solver.expand_structural_hits_to_top_k
        cp_model.CpSolver.solve = timed_solve
        solver._build_model = timed_build
        policy_ladder_tier_step.probe_degrade_aggregate_rewrites = timed_probe
        policy_ladder_tier_step.solve_inference_problem = timed_solve_problem
        policy_ladder_tier_step.build_action_catalog_from_turn = timed_catalog
        solver.merge_score_equivalent_combos = timed_span("merge", original_merge)
        solver.expand_structural_hits_to_top_k = timed_span("expand", original_expand)
        original_build_problem = policy_ladder_tier_step.build_inference_problem
        original_constrain = actions._apply_combo_count_constraints
        original_validate = solver._validate_problem
        original_collect = solver.collect_near_best_structural_hits
        from api.analytics.military_score_inference import near_best_structural_search as near_best

        band_collector = near_best._ObjectiveBandCollector
        original_on_solution = band_collector.on_solution_callback

        def timed_on_solution(callback_self, *args, **kwargs):
            started = time.perf_counter()
            try:
                return original_on_solution(callback_self, *args, **kwargs)
            finally:
                report.band_callbacks += 1
                report.band_callback_seconds += time.perf_counter() - started

        band_collector.on_solution_callback = timed_on_solution
        self._band_collector_type = band_collector
        self._original_on_solution = original_on_solution

        original_read_combos = near_best._read_combo_counts
        original_seed_cuts = near_best.seed_no_good_cuts_for_held_solutions
        policy_ladder_tier_step.build_inference_problem = timed_span(
            "build_problem",
            original_build_problem,
        )
        actions._apply_combo_count_constraints = timed_span(
            "constrain_combos",
            original_constrain,
        )
        solver._validate_problem = timed_span("validate", original_validate)
        solver.collect_near_best_structural_hits = timed_span("collect_hits", original_collect)
        near_best._read_combo_counts = timed_span("read_combos", original_read_combos)
        near_best.seed_no_good_cuts_for_held_solutions = timed_span(
            "seed_cuts",
            original_seed_cuts,
        )
        original_step_leftover = policy_ladder_tier_step.leftover_military_2x
        original_family_leftover = ship_first_family.leftover_military_2x
        original_non_torp = ship_first_family.non_torp_military_2x
        original_step_lookups = policy_ladder_tier_step.catalog_score_lookups
        original_ladder_lookups = policy_ladder.catalog_score_lookups
        original_payload_lookups = inference_api_payload.catalog_score_lookups
        policy_ladder_tier_step.catalog_score_lookups = timed_span(
            "score_lookups",
            original_step_lookups,
        )
        policy_ladder.catalog_score_lookups = timed_span(
            "score_lookups",
            original_ladder_lookups,
        )
        inference_api_payload.catalog_score_lookups = timed_span(
            "score_lookups",
            original_payload_lookups,
        )
        policy_ladder_tier_step.leftover_military_2x = timed_span(
            "leftover_lookup",
            original_step_leftover,
        )
        ship_first_family.leftover_military_2x = timed_span(
            "leftover_lookup",
            original_family_leftover,
        )
        ship_first_family.non_torp_military_2x = timed_span(
            "non_torp_lookup",
            original_non_torp,
        )
        from api.analytics.military_score_inference import (
            analytic,
            inference_row_runner,
            row_complete_factory,
        )

        completion_bindings = (
            (inference_row_runner, "run_policy_ladder_tier_step", "tier_step"),
            (inference_row_runner, "_outcome_after_ladder_complete", "ladder_complete"),
            (inference_row_runner, "finalize_policy_ladder_result", "finalize"),
            (inference_row_runner, "row_complete_from_ladder_finalize", "row_complete"),
            (policy_ladder_tier_step, "finish_tier_step", "finish_step"),
            (policy_ladder, "leftover_0_solutions", "leftover_0"),
            (policy_ladder, "worthwhile_remainder_bound_for_turn", "remainder_bound"),
            (row_complete_factory, "inference_result_to_api_payload", "api_payload"),
            (row_complete_factory, "row_complete_wire_payload_from_api_payload", "wire_from_api"),
            (analytic, "build_inference_solver_diagnostics", "solver_diagnostics"),
            (analytic, "catalog_to_actions_payload", "catalog_payload"),
            (inference_api_payload, "inference_api_payload", "wire_payload"),
            (inference_api_payload, "_serialize_solution_with_arithmetic", "serialize_solution"),
            (
                inference_api_payload,
                "solution_military_score_arithmetic_payload",
                "score_arithmetic",
            ),
        )
        from api.analytics.military_score_inference import worthwhile_remainder_bound
        from api.analytics.military_score_inference.prior_mining import mine_stock

        completion_bindings = (
            *completion_bindings,
            (worthwhile_remainder_bound, "load_mine_stock_for_category", "mine_stock_load"),
            (
                worthwhile_remainder_bound,
                "compute_worthwhile_remainder_bound",
                "remainder_compute",
            ),
            (mine_stock, "load_mine_stock_asset", "mine_stock_asset"),
            (mine_stock, "parse_mine_stock_document", "histogram_parse"),
        )
        completion_patches: list[tuple[object, str, object]] = []
        for module, attr, name in completion_bindings:
            original = getattr(module, attr)
            setattr(module, attr, timed_span(name, original))
            completion_patches.append((module, attr, original))
        self._completion_patches = completion_patches
        self._solver_module = solver
        self._original_build = original_build
        self._tier_step_module = policy_ladder_tier_step
        self._original_probe = original_probe
        self._original_solve_problem = original_solve_problem
        self._original_catalog = original_catalog
        self._original_merge = original_merge
        self._original_expand = original_expand
        self._family_module = ship_first_family
        self._ladder_module = policy_ladder
        self._payload_module = inference_api_payload
        self._original_step_leftover = original_step_leftover
        self._original_family_leftover = original_family_leftover
        self._original_non_torp = original_non_torp
        self._original_step_lookups = original_step_lookups
        self._original_ladder_lookups = original_ladder_lookups
        self._original_payload_lookups = original_payload_lookups
        self._actions_module = actions
        self._original_build_problem = original_build_problem
        self._original_constrain = original_constrain
        self._original_validate = original_validate
        self._original_collect = original_collect
        self._near_best_module = near_best
        self._original_read_combos = original_read_combos
        self._original_seed_cuts = original_seed_cuts
        self._installed = True

    def restore(self) -> None:
        if not self._installed:
            return
        cp_model.CpSolver.solve = self._original_solve
        self._solver_module._build_model = self._original_build
        self._tier_step_module.probe_degrade_aggregate_rewrites = self._original_probe
        self._tier_step_module.solve_inference_problem = self._original_solve_problem
        self._tier_step_module.build_action_catalog_from_turn = self._original_catalog
        self._solver_module.merge_score_equivalent_combos = self._original_merge
        self._solver_module.expand_structural_hits_to_top_k = self._original_expand
        self._tier_step_module.leftover_military_2x = self._original_step_leftover
        self._family_module.leftover_military_2x = self._original_family_leftover
        self._family_module.non_torp_military_2x = self._original_non_torp
        self._tier_step_module.catalog_score_lookups = self._original_step_lookups
        self._ladder_module.catalog_score_lookups = self._original_ladder_lookups
        self._payload_module.catalog_score_lookups = self._original_payload_lookups
        self._tier_step_module.build_inference_problem = self._original_build_problem
        self._actions_module._apply_combo_count_constraints = self._original_constrain
        self._solver_module._validate_problem = self._original_validate
        self._solver_module.collect_near_best_structural_hits = self._original_collect
        self._near_best_module._read_combo_counts = self._original_read_combos
        self._near_best_module.seed_no_good_cuts_for_held_solutions = self._original_seed_cuts
        self._band_collector_type.on_solution_callback = self._original_on_solution
        for module, attr, original in self._completion_patches:
            setattr(module, attr, original)
        self._installed = False


def _solver_int(solver: cp_model.CpSolver, name: str) -> int:
    try:
        value = getattr(solver, name)
    except RuntimeError, AttributeError:
        return 0
    if callable(value):
        try:
            value = value()
        except RuntimeError, TypeError, ValueError:
            return 0
    try:
        return int(value)
    except TypeError, ValueError:
        return 0


def _read_object(storage: StorageBackend, key: str) -> dict | None:
    try:
        value = storage.get(key)
    except NotFoundError:
        return None
    if not isinstance(value, dict):
        return None
    return value


def _prior_fleet_resolution(
    storage: StorageBackend,
    *,
    game_id: int,
    perspective: int,
    turn_number: int,
    player_id: int,
    prior_turn: TurnInfo,
) -> PriorTurnFleetTorpResolution:
    """Load the ensure-final prior-turn fleet ledger the live tier wire applies."""
    persistence = FleetSnapshotPersistenceService
    prior_turn_number = turn_number - 1
    ledger_raw = _read_object(
        storage,
        persistence.ledger_key(game_id, perspective, prior_turn_number, player_id),
    )
    if ledger_raw is None:
        return PriorTurnFleetTorpResolution(overlay=None, input_status="unavailable")
    persisted = persisted_fleet_ledger_from_json(ledger_raw)
    mark_raw = _read_object(
        storage,
        persistence.evidence_mark_key(game_id, perspective, player_id),
    )
    mark = fleet_evidence_mark_from_json(mark_raw) if mark_raw is not None else FleetEvidenceMark()
    if not fleet_ledger_is_ensure_final(persisted, turn_number=prior_turn_number, mark=mark):
        return PriorTurnFleetTorpResolution(overlay=None, input_status="unavailable")
    snapshot = FleetTurnSnapshot(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=game_id,
        perspective=perspective,
        turn=prior_turn_number,
        players=[persisted.ledger],
    )
    records = records_for_scope(
        snapshot,
        ExportScope(
            game_id=game_id,
            perspective=perspective,
            turn=prior_turn_number,
            player_id=player_id,
        ),
    )
    return resolution_from_fleet_records(records, prior_turn=prior_turn)


def reproduce_admit_ship_outlier(
    storage: StorageBackend,
    *,
    game_id: int = GAME_ID,
    perspective: int = PERSPECTIVE,
    turn_number: int = TURN,
    player_id: int = PLAYER_ID,
    through_tier_index: int = OUTLIER_TIER_INDEX,
    load_counterparty_fleets: bool = False,
) -> OutlierReproduction:
    """Run scores tiers 0..``through_tier_index`` for one stored row.

    Uses ``run_scores_tier_solve`` on a ``RowRun`` built the same way as the
    occupancy probe, plus the prior-turn fleet overlay the live wire applies.
    Stops when that tier finishes or the ladder reaches a terminal outcome.
    Does not persist.
    """
    turn = _load_turn(storage, game_id, perspective, turn_number)
    score = next(row for row in turn.scores if row.ownerid == player_id)
    skip = resolve_inference_admission_skip(turn, player_id, perspective=perspective)
    if skip is not None:
        raise RuntimeError(f"player {player_id} is not admitted: {skip}")

    def load_scoreboard_turn(host_turn: int) -> TurnInfo | None:
        try:
            return _load_turn(storage, game_id, perspective, host_turn)
        except NotFoundError:
            return None

    prior_turn = load_scoreboard_turn(turn_number - 1)
    if prior_turn is None:
        resolution = PriorTurnFleetTorpResolution(overlay=None, input_status="unavailable")
    else:
        resolution = _prior_fleet_resolution(
            storage,
            game_id=game_id,
            perspective=perspective,
            turn_number=turn_number,
            player_id=player_id,
            prior_turn=prior_turn,
        )
    session = InferenceRowStreamSession(
        player_id=player_id,
        observation=build_inference_observation(
            score,
            turn,
            load_scoreboard_turn=load_scoreboard_turn,
        ),
        turn=turn,
        game_id=game_id,
        perspective=perspective,
        turn_number=turn.settings.turn,
        load_scoreboard_turn=load_scoreboard_turn,
    )
    if load_counterparty_fleets:
        from api.analytics.export_context import make_analytic_query_context
        from api.analytics.fleet.compute_services import FleetComputeServices
        from api.analytics.options import TurnAnalyticsOptions

        session.query_context = make_analytic_query_context(
            turn,
            TurnAnalyticsOptions(),
            game_id=game_id,
            perspective=perspective,
            load_turn=load_scoreboard_turn,
            export_services={
                FLEET_ANALYTIC_ID: FleetComputeServices(
                    persistence=FleetSnapshotPersistenceService(storage),
                    game_id=game_id,
                    perspective=perspective,
                    load_turn=load_scoreboard_turn,
                )
            },
        )
    observation = session.observation
    report = OutlierReproduction(
        fleet_input_status=resolution.input_status,
        record_count=len(resolution.records),
        military_delta_2x=observation.military_delta_2x,
        warship_delta=observation.warship_delta,
        freighter_delta=observation.freighter_delta,
        starbases_owned=observation.starbases_owned,
    )
    run = RowRun(session)
    _apply_fleet_resolution_to_row_run(run, resolution)
    from api.analytics.scores.tier_row_run_registry import register_row_run

    register_row_run(run)
    probe = _PhaseProbe(report)
    probe.install()
    try:
        while True:
            state = run.ladder_state
            if state is None or state.ladder_complete:
                break
            if state.next_step_index > through_tier_index:
                break
            tier_index = state.next_step_index
            tier_id = state.policy_steps[tier_index].id
            tier_token = _active_tier.set(f"{tier_index}:{tier_id}")
            started = time.perf_counter()
            try:
                result = run_scores_tier_solve({"runId": run.run_id})
            finally:
                _active_tier.reset(tier_token)
            wall_seconds = time.perf_counter() - started
            diagnostics = state.step_diagnostics[-1] if state.step_diagnostics else {}
            last = state.last_diagnostics
            report.tiers.append(
                TierSample(
                    index=tier_index,
                    tier_id=tier_id,
                    wall_seconds=wall_seconds,
                    outcome=result.outcome,
                    combo_count=_as_int(diagnostics.get("comboCount")),
                    stopped_reason=str(last.get("stopped_reason", "")),
                    solve_wall_seconds=_as_float(last.get("solveWallSeconds")),
                    deterministic_time=_as_float(last.get("deterministicTime")),
                    structural_hits=_as_int(last.get("structural_hit_count")),
                )
            )
            if result.outcome != "continue" or tier_index >= through_tier_index:
                break
    finally:
        probe.restore()
    finished = run.ladder_state
    if finished is not None:
        report.solution_action_ids = [
            tuple(action.action_id for action in solution.actions)
            for solution in finished.merged_solutions
        ]
        report.solution_families = [
            solution.ship_first_family for solution in finished.merged_solutions
        ]
    return report


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _as_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def format_outlier_report(
    report: OutlierReproduction,
    *,
    diagnostic_loaded_wall_seconds: float = DIAGNOSTIC_LOADED_WALL_SECONDS,
) -> str:
    lines = [
        (
            f"diagnostic_loaded_wall={diagnostic_loaded_wall_seconds:.2f}s "
            "(8 busy workers) "
            f"fleet_input_status={report.fleet_input_status} records={report.record_count} "
            f"military_2x={report.military_delta_2x} warships={report.warship_delta} "
            f"freighters={report.freighter_delta} starbases={report.starbases_owned}"
        ),
        "tiers:",
    ]
    for tier in report.tiers:
        lines.append(
            "  "
            f"{tier.index} {tier.tier_id:28} "
            f"wall={tier.wall_seconds:8.2f}s "
            f"solve={tier.solve_wall_seconds:8.2f}s "
            f"det={tier.deterministic_time:7.3f} "
            f"combos={tier.combo_count:6d} "
            f"hits={tier.structural_hits:2d} "
            f"stop={tier.stopped_reason} "
            f"outcome={tier.outcome}"
        )
    if report.solution_action_ids:
        lines.append("solutions:")
        for action_ids, family in zip(
            report.solution_action_ids,
            report.solution_families,
            strict=True,
        ):
            lines.append(f"  {family} {', '.join(action_ids)}")
    lines.append("builds:")
    for build in report.builds:
        lines.append(
            "  "
            f"{build.tier:32} {build.phase:12} "
            f"wall={build.wall_seconds:8.3f}s "
            f"vars={build.variables:7d} "
            f"constraints={build.constraints:7d} "
            f"combos={build.combos:6d}"
        )
    solves = sorted(report.solves, key=lambda sample: sample.wall_seconds, reverse=True)
    structural = [sample for sample in report.solves if sample.phase == "structural"]
    degrade = [sample for sample in report.solves if sample.phase == "degrade"]
    lines.append(
        "solves: "
        f"n={len(report.solves)} "
        f"structural_wall={sum(sample.wall_seconds for sample in structural):.2f}s "
        f"degrade_wall={sum(sample.wall_seconds for sample in degrade):.2f}s "
        f"build_wall={sum(sample.wall_seconds for sample in report.builds):.2f}s"
    )
    if report.notes:
        lines.append("catalogs:")
        lines.extend(f"  {note}" for note in report.notes)
    lines.append(
        f"band callbacks: n={report.band_callbacks} wall={report.band_callback_seconds:.3f}s"
    )
    lines.append("spans:")
    span_totals: dict[tuple[str, str], float] = {}
    span_counts: dict[tuple[str, str], int] = {}
    for span in report.spans:
        key = (span.tier, span.name)
        span_totals[key] = span_totals.get(key, 0.0) + span.wall_seconds
        span_counts[key] = span_counts.get(key, 0) + 1
    for (tier, name), wall in sorted(span_totals.items(), key=lambda item: item[1], reverse=True):
        lines.append(f"  {tier:32} {name:10} n={span_counts[(tier, name)]:3d} wall={wall:8.2f}s")
    for prefix in ("4:", "5:", "6:"):
        tier_solves = [sample for sample in report.solves if sample.tier.startswith(prefix)]
        if not tier_solves:
            continue
        tier_wall = sum(sample.wall_seconds for sample in tier_solves)
        det = sum(sample.deterministic_time for sample in tier_solves)
        statuses = Counter(sample.status for sample in tier_solves)
        status_text = " ".join(f"{status}={count}" for status, count in statuses.most_common())
        lines.append(
            f"tier {prefix[0]} solves: n={len(tier_solves)} wall={tier_wall:.2f}s "
            f"mean={tier_wall / len(tier_solves):.2f}s det_sum={det:.3f} {status_text}"
        )
    lines.append("slowest solves:")
    for sample in solves[:12]:
        lines.append(
            "  "
            f"{sample.wall_seconds:8.2f}s "
            f"det={sample.deterministic_time:7.3f} "
            f"{sample.phase:12} {sample.tier:32} "
            f"{sample.status:10} "
            f"bools={sample.booleans:7d} "
            f"conflicts={sample.conflicts:8d} "
            f"branches={sample.branches:8d}"
        )
    return "\n".join(lines)


def test_turn10_player46_admit_ship_torpedoes_reproduces_diagnostic_outlier() -> None:
    if os.environ.get("SCORES_OUTLIER_REPRO") != "1":
        pytest.skip("set SCORES_OUTLIER_REPRO=1 to reproduce the local 96s tier")
    storage_root = Path(os.environ.get("SCORES_OUTLIER_STORAGE", DEFAULT_STORAGE_ROOT))
    if not storage_root.is_dir():
        pytest.skip(f"storage root not found: {storage_root}")

    from tests.inference_corpus.storage_loader import configure_file_storage

    previous_config = get_config()
    reset_tier_row_run_registry_for_tests()
    try:
        storage = configure_file_storage(storage_root=storage_root)
        report = reproduce_admit_ship_outlier(storage)
    finally:
        reset_tier_row_run_registry_for_tests()
        set_config(previous_config)
        clear_backend_cache()

    rendered = format_outlier_report(report)
    print(rendered)
    outlier = report.tier(OUTLIER_TIER_INDEX)
    assert outlier is not None, f"ladder stopped before tier 4\n{rendered}"
    assert outlier.tier_id == OUTLIER_TIER_ID, rendered
    assert outlier.stopped_reason == "max_solutions", rendered
    assert outlier.deterministic_time < 0.9, rendered
    assert 30_000 <= outlier.combo_count <= 50_000, rendered
    assert outlier.wall_seconds >= IDLE_MINIMUM_WALL_SECONDS, rendered
    tier4_solves = [sample for sample in report.solves if sample.tier.startswith("4:")]
    assert len(tier4_solves) >= 10, rendered


def test_turn3_player10_admit_ship_torpedoes_reproduces_early_outlier() -> None:
    """Idle reproduction of the loaded 31.6 s admit-ship step on turn 3 player 10.

    The loaded duration was this step while 8 workers were busy. An idle run
    checks the partial-slot catalog, that the tier still searches, and that it
    stops by filling its solution cap.
    """
    if os.environ.get("SCORES_OUTLIER_REPRO") != "1":
        pytest.skip("set SCORES_OUTLIER_REPRO=1 to reproduce the local early-sweep tier")
    storage_root = Path(os.environ.get("SCORES_OUTLIER_STORAGE", DEFAULT_STORAGE_ROOT))
    if not storage_root.is_dir():
        pytest.skip(f"storage root not found: {storage_root}")

    from tests.inference_corpus.storage_loader import configure_file_storage

    previous_config = get_config()
    reset_tier_row_run_registry_for_tests()
    try:
        storage = configure_file_storage(storage_root=storage_root)
        report = reproduce_admit_ship_outlier(
            storage,
            turn_number=3,
            player_id=10,
            through_tier_index=OUTLIER_TIER_INDEX,
        )
    finally:
        reset_tier_row_run_registry_for_tests()
        set_config(previous_config)
        clear_backend_cache()

    rendered = format_outlier_report(
        report,
        diagnostic_loaded_wall_seconds=TURN3_PLAYER10_LOADED_WALL_SECONDS,
    )
    print(rendered)
    outlier = report.tier(OUTLIER_TIER_INDEX)
    assert outlier is not None, f"ladder stopped before tier 4\n{rendered}"
    assert outlier.tier_id == OUTLIER_TIER_ID, rendered
    assert outlier.wall_seconds >= 0.5, rendered
    assert outlier.combo_count >= 10_000, rendered
    assert outlier.outcome == "continue", rendered
    assert outlier.stopped_reason == "max_solutions", rendered
    assert outlier.structural_hits == 5, rendered
    tier4_solves = [sample for sample in report.solves if sample.tier.startswith("4:")]
    assert len(tier4_solves) >= 5, rendered


def test_turn10_player51_solve_reproduces_late_outlier() -> None:
    """Idle reproduction of the turn 10 player 51 ladder through full_components.

    Loaded walls while 8 workers were busy: admit_ship 30.8 s, planet defense
    12.0 s, full_components 13.0 s. The row's completed node stopped on tier 6.
    """
    if os.environ.get("SCORES_OUTLIER_REPRO") != "1":
        pytest.skip("set SCORES_OUTLIER_REPRO=1 to reproduce the local late-window row")
    storage_root = Path(os.environ.get("SCORES_OUTLIER_STORAGE", DEFAULT_STORAGE_ROOT))
    if not storage_root.is_dir():
        pytest.skip(f"storage root not found: {storage_root}")

    from tests.inference_corpus.storage_loader import configure_file_storage

    previous_config = get_config()
    reset_tier_row_run_registry_for_tests()
    try:
        storage = configure_file_storage(storage_root=storage_root)
        report = reproduce_admit_ship_outlier(
            storage,
            turn_number=10,
            player_id=51,
            through_tier_index=TURN10_PLAYER51_THROUGH_TIER_INDEX,
        )
    finally:
        reset_tier_row_run_registry_for_tests()
        set_config(previous_config)
        clear_backend_cache()

    rendered = format_outlier_report(
        report,
        diagnostic_loaded_wall_seconds=TURN10_PLAYER51_ADMIT_LOADED_WALL_SECONDS,
    )
    print(rendered)
    admit = report.tier(OUTLIER_TIER_INDEX)
    assert admit is not None, f"ladder stopped before tier 4\n{rendered}"
    assert admit.tier_id == OUTLIER_TIER_ID, rendered
    assert admit.wall_seconds >= 1.0, rendered
    assert admit.combo_count >= 10_000, rendered
    full_components = report.tier(TURN10_PLAYER51_THROUGH_TIER_INDEX)
    assert full_components is not None, f"ladder stopped before tier 6\n{rendered}"
    assert full_components.tier_id == "full_components", rendered


def test_turn15_player38_modest_planet_defense_reproduces_late3_outlier() -> None:
    """Turn 15 player 38 planet defense does not enumerate a negative score band.

    The loaded step was 20.8 s while 8 workers were busy. The catalog has no
    ship combos and the observed military score is negative, so the under-explain
    band is skipped instead of searched.
    """
    if os.environ.get("SCORES_OUTLIER_REPRO") != "1":
        pytest.skip("set SCORES_OUTLIER_REPRO=1 to reproduce the local late-window row")
    storage_root = Path(os.environ.get("SCORES_OUTLIER_STORAGE", DEFAULT_STORAGE_ROOT))
    if not storage_root.is_dir():
        pytest.skip(f"storage root not found: {storage_root}")

    from tests.inference_corpus.storage_loader import configure_file_storage

    previous_config = get_config()
    reset_tier_row_run_registry_for_tests()
    try:
        storage = configure_file_storage(storage_root=storage_root)
        report = reproduce_admit_ship_outlier(
            storage,
            turn_number=15,
            player_id=38,
            through_tier_index=TURN15_PLAYER38_MODEST_TIER_INDEX,
        )
    finally:
        reset_tier_row_run_registry_for_tests()
        set_config(previous_config)
        clear_backend_cache()

    rendered = format_outlier_report(
        report,
        diagnostic_loaded_wall_seconds=TURN15_PLAYER38_MODEST_LOADED_WALL_SECONDS,
    )
    print(rendered)
    modest = report.tier(TURN15_PLAYER38_MODEST_TIER_INDEX)
    assert modest is not None, f"ladder stopped before tier 5\n{rendered}"
    assert modest.tier_id == "modest_planet_defense", rendered
    assert modest.combo_count == 0, rendered
    assert modest.structural_hits == 0, rendered
    assert modest.outcome == "continue", rendered
    heavy = [
        sample
        for sample in report.solves
        if sample.tier.startswith("5:") and sample.branches >= 10_000
    ]
    assert not heavy, rendered


def test_turn8_player9_incoming_warship_floor_skips_torpedo_plateau() -> None:
    """Turn 8 player 9 emits donor transfers from hull floors and does not search.

    The loaded admit step was 125.9 s on a saturated pool. Idle, that same
    search spent the full 1.0 deterministic allowance (about 0.39 s, 50692
    branches, 20 torpedo-plateau hits). With donor hull floors the ladder
    stops on the first tier.
    """
    if os.environ.get("SCORES_OUTLIER_REPRO") != "1":
        pytest.skip("set SCORES_OUTLIER_REPRO=1 to reproduce the local late-window row")
    storage_root = Path(os.environ.get("SCORES_OUTLIER_STORAGE", DEFAULT_STORAGE_ROOT))
    if not storage_root.is_dir():
        pytest.skip(f"storage root not found: {storage_root}")

    from tests.inference_corpus.storage_loader import configure_file_storage

    previous_config = get_config()
    reset_tier_row_run_registry_for_tests()
    try:
        storage = configure_file_storage(storage_root=storage_root)
        report = reproduce_admit_ship_outlier(
            storage,
            turn_number=8,
            player_id=9,
            through_tier_index=OUTLIER_TIER_INDEX,
            load_counterparty_fleets=True,
        )
    finally:
        reset_tier_row_run_registry_for_tests()
        set_config(previous_config)
        clear_backend_cache()

    rendered = format_outlier_report(
        report,
        diagnostic_loaded_wall_seconds=TURN8_PLAYER9_ADMIT_LOADED_WALL_SECONDS,
    )
    print(rendered)
    assert len(report.tiers) == 1, rendered
    first = report.tiers[0]
    assert first.index == 0, rendered
    assert first.combo_count == 0, rendered
    assert first.stopped_reason == "incoming_warship_floor", rendered
    assert first.deterministic_time == 0.0, rendered
    assert first.wall_seconds < 1.0, rendered
    assert report.solves == [], rendered
    assert report.solution_action_ids == [
        ("acquired:warship:from:14",),
        ("acquired:warship:from:16",),
        ("acquired:warship:from:48",),
    ], rendered
    assert report.solution_families == ["mine_overshoot", "mine_overshoot", "mine_overshoot"]


def test_turn15_player28_admit_ship_torpedoes_reproduces_late6_outlier() -> None:
    """Idle reproduction of the longest admit step in the late-6 tail.

    diagnostics_late6.json records turn 15 player 28 ``admit_ship_torpedoes``
    at 13.38 s of worker time. An idle run of the same step is 11.57 s, still
    spending the full 1.0 deterministic allowance on 57,780 ship combos.
    """
    if os.environ.get("SCORES_OUTLIER_REPRO") != "1":
        pytest.skip("set SCORES_OUTLIER_REPRO=1 to reproduce the local late-window row")
    storage_root = Path(os.environ.get("SCORES_OUTLIER_STORAGE", DEFAULT_STORAGE_ROOT))
    if not storage_root.is_dir():
        pytest.skip(f"storage root not found: {storage_root}")

    from tests.inference_corpus.storage_loader import configure_file_storage

    previous_config = get_config()
    reset_tier_row_run_registry_for_tests()
    try:
        storage = configure_file_storage(storage_root=storage_root)
        report = reproduce_admit_ship_outlier(
            storage,
            turn_number=15,
            player_id=28,
            through_tier_index=OUTLIER_TIER_INDEX,
        )
    finally:
        reset_tier_row_run_registry_for_tests()
        set_config(previous_config)
        clear_backend_cache()

    rendered = format_outlier_report(
        report,
        diagnostic_loaded_wall_seconds=TURN15_PLAYER28_ADMIT_LOADED_WALL_SECONDS,
    )
    print(rendered)
    admit = report.tier(OUTLIER_TIER_INDEX)
    assert admit is not None, f"ladder stopped before tier 4\n{rendered}"
    assert admit.tier_id == OUTLIER_TIER_ID, rendered
    assert admit.combo_count == 57_780, rendered
    assert admit.stopped_reason == "time_budget", rendered
    assert admit.wall_seconds >= 5.0, rendered
    assert admit.deterministic_time >= 0.9, rendered


def test_turn10_player4_admit_ship_torpedoes_reproduces_late8_median() -> None:
    """Idle reproduction of a median late-8 admit_ship_torpedoes step.

    The persisted emission is 1.684s, time-limited, on 13,365 ship combos.
    The two central observations of the 530-step distribution are this row
    and turn 11 player 20 at 1.692s. Unfiltered, the idle step spent the
    deterministic budget in presolve. Reachable fittings leave a model that
    finishes the band and stops at the solution cap.
    """
    if os.environ.get("SCORES_OUTLIER_REPRO") != "1":
        pytest.skip("set SCORES_OUTLIER_REPRO=1 to reproduce the local late-window row")
    storage_root = Path(os.environ.get("SCORES_OUTLIER_STORAGE", DEFAULT_STORAGE_ROOT))
    if not storage_root.is_dir():
        pytest.skip(f"storage root not found: {storage_root}")

    from tests.inference_corpus.storage_loader import configure_file_storage

    previous_config = get_config()
    reset_tier_row_run_registry_for_tests()
    try:
        storage = configure_file_storage(storage_root=storage_root)
        report = reproduce_admit_ship_outlier(
            storage,
            turn_number=10,
            player_id=4,
            through_tier_index=OUTLIER_TIER_INDEX,
        )
    finally:
        reset_tier_row_run_registry_for_tests()
        set_config(previous_config)
        clear_backend_cache()

    rendered = format_outlier_report(
        report,
        diagnostic_loaded_wall_seconds=TURN10_PLAYER4_ADMIT_LOADED_WALL_SECONDS,
    )
    print(rendered)
    admit = report.tier(OUTLIER_TIER_INDEX)
    assert admit is not None, f"ladder stopped before tier 4\n{rendered}"
    assert admit.tier_id == OUTLIER_TIER_ID, rendered
    assert admit.combo_count == TURN10_PLAYER4_ADMIT_COMBO_COUNT, rendered
    assert admit.stopped_reason == "max_solutions", rendered
    assert admit.structural_hits == 20, rendered
    assert admit.deterministic_time < 0.5, rendered
    assert admit.wall_seconds < 0.75, rendered
