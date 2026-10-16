"""Opt-in harness for local scores outlier reproductions.

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
        tests/test_scores_admit_ship_torpedo_outliers.py \\
        tests/test_scores_planet_defense_outlier.py \\
        tests/test_scores_late_window_solve_outlier.py \\
        tests/test_scores_incoming_warship_floor_outlier.py \\
        -s

``SCORES_OUTLIER_STORAGE`` overrides the file-store root. The default is
``.data`` at the repo root.
"""

from __future__ import annotations

import os
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from api.analytics.export_context import make_analytic_query_context
from api.analytics.export_types import ExportScope
from api.analytics.fleet.compute_services import FleetComputeServices
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
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.compute_orchestration import (
    _apply_fleet_resolution_to_row_run,
    run_scores_tier_solve,
)
from api.analytics.scores.tier_row_run_registry import (
    register_row_run,
    reset_tier_row_run_registry_for_tests,
)
from api.analytics.scores.tier_solve_jobs import _load_turn
from api.config import get_config, set_config
from api.errors import NotFoundError
from api.models.game import TurnInfo
from api.storage.base import StorageBackend
from api.storage_factory import clear_backend_cache

from tests.inference_corpus.storage_loader import configure_file_storage
from tests.scores_outlier_repro_probe import OutlierReproduction, PhaseProbe, TierSample

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


@pytest.fixture
def outlier_repro_storage() -> Path:
    """File-store root for an opt-in scores outlier reproduction.

    Skips unless ``SCORES_OUTLIER_REPRO`` is ``1``. The root is
    ``SCORES_OUTLIER_STORAGE`` when set, otherwise ``DEFAULT_STORAGE_ROOT``.
    """
    if os.environ.get("SCORES_OUTLIER_REPRO") != "1":
        pytest.skip("set SCORES_OUTLIER_REPRO=1 to reproduce local scores outlier tiers")
    storage_root = Path(os.environ.get("SCORES_OUTLIER_STORAGE", DEFAULT_STORAGE_ROOT))
    if not storage_root.is_dir():
        pytest.skip(f"storage root not found: {storage_root}")
    return storage_root


@contextmanager
def open_outlier_repro_storage(storage_root: Path) -> Iterator[StorageBackend]:
    """Point process storage at ``storage_root`` for one reproduction.

    Restores config, the tier row-run registry, and the storage backend cache
    when the reproduction finishes.
    """
    previous_config = get_config()
    reset_tier_row_run_registry_for_tests()
    try:
        yield configure_file_storage(storage_root=storage_root)
    finally:
        reset_tier_row_run_registry_for_tests()
        set_config(previous_config)
        clear_backend_cache()


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
    register_row_run(run)
    probe = PhaseProbe(report)
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
            with probe.measure_tier(tier_index, tier_id):
                started = time.perf_counter()
                result = run_scores_tier_solve({"runId": run.run_id})
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
