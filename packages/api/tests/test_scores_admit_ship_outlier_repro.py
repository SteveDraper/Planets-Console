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
        original_merge = solver.merge_score_equivalent_combos
        original_expand = solver.expand_structural_hits_to_top_k
        cp_model.CpSolver.solve = timed_solve
        solver._build_model = timed_build
        policy_ladder_tier_step.probe_degrade_aggregate_rewrites = timed_probe
        policy_ladder_tier_step.solve_inference_problem = timed_solve_problem
        policy_ladder_tier_step.build_action_catalog_from_turn = timed_span(
            "catalog",
            original_catalog,
        )
        solver.merge_score_equivalent_combos = timed_span("merge", original_merge)
        solver.expand_structural_hits_to_top_k = timed_span("expand", original_expand)
        original_build_problem = policy_ladder_tier_step.build_inference_problem
        original_constrain = actions._apply_combo_count_constraints
        original_validate = solver._validate_problem
        original_collect = solver.collect_near_best_structural_hits
        from api.analytics.military_score_inference import near_best_structural_search as near_best

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
    lines.append("spans:")
    span_totals: dict[tuple[str, str], float] = {}
    span_counts: dict[tuple[str, str], int] = {}
    for span in report.spans:
        key = (span.tier, span.name)
        span_totals[key] = span_totals.get(key, 0.0) + span.wall_seconds
        span_counts[key] = span_counts.get(key, 0) + 1
    for (tier, name), wall in sorted(span_totals.items(), key=lambda item: item[1], reverse=True):
        lines.append(f"  {tier:32} {name:10} n={span_counts[(tier, name)]:3d} wall={wall:8.2f}s")
    tier4_solves = [sample for sample in report.solves if sample.tier.startswith("4:")]
    if tier4_solves:
        tier4_wall = sum(sample.wall_seconds for sample in tier4_solves)
        lines.append(
            f"tier4 solves: n={len(tier4_solves)} wall={tier4_wall:.2f}s "
            f"mean={tier4_wall / len(tier4_solves):.2f}s"
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
