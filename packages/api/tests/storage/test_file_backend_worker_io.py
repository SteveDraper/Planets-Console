"""File-backend worker I/O accounting and GIL convoy characterization."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from api.analytics.export_context import make_analytic_query_context
from api.analytics.fleet.chain import ensure_fleet_baseline_for_player
from api.analytics.fleet.compute_orchestration import (
    FleetPersistencePolicy,
    build_fleet_materialization_leg_job_wire,
)
from api.analytics.fleet.compute_plane.observation_leg import run_fleet_observation_leg
from api.analytics.fleet.compute_services import FleetComputeServices
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.serialization import (
    fleet_acquisition_ledger_to_json,
    persisted_fleet_ledger_to_json,
)
from api.analytics.fleet.types import (
    FleetMaterializationProvenance,
    PersistedFleetLedger,
)
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.prior_fleet_resolution import resolve_prior_fleet_for_scores
from api.compute.scope import ComputeScope
from api.compute.wire import DependencyOutputs
from api.serialization.inference_row_persistence import PersistedInferenceRow
from api.serialization.turn import turn_info_to_json
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.file import FileStorageBackend
from tests.file_backend_io_accounting import (
    ANALYTIC_SIBLINGS,
    ANALYTICS_PREFIX,
    FLEET_KEY,
    GAME_ID,
    PERSPECTIVE,
    TURN_KEY,
    TURN_NUMBER,
    TURNS_PREFIX,
    CountingStorageBackend,
    FileIoCounts,
    count_file_backend_syscalls,
    make_counting_file_backend,
    seed_file_store_tree,
)
from tests.scores_exports_helpers import first_player_id

WORKER_COUNT = 8
FILE_MIX_ITERS = 400
SLEEP_SECONDS = 0.12
SLEEP_MIN_THROUGHPUT_RATIO = 4.0
FILE_MAX_THROUGHPUT_RATIO = 3.0


def _file_backend(tmp_path: Path) -> FileStorageBackend:
    root = tmp_path / "data"
    root.mkdir()
    backend = FileStorageBackend(root)
    seed_file_store_tree(backend)
    return backend


def _counting_seeded_backend(tmp_path: Path) -> tuple[CountingStorageBackend, FileIoCounts]:
    root = tmp_path / "data"
    root.mkdir()
    counting, counts = make_counting_file_backend(root)
    seed_file_store_tree(counting)
    counts.reset()
    return counting, counts


def _fleet_ctx(sample_turn, persistence: FleetSnapshotPersistenceService):
    prior_turn_number = sample_turn.settings.turn - 1
    prior_turn = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=prior_turn_number),
        game=replace(sample_turn.game, turn=prior_turn_number),
    )
    stored = {
        sample_turn.settings.turn: sample_turn,
        prior_turn_number: prior_turn,
    }

    def load_turn(turn_number: int):
        return stored.get(turn_number)

    services = FleetComputeServices(
        persistence=persistence,
        game_id=GAME_ID,
        perspective=PERSPECTIVE,
        load_turn=load_turn,
    )
    return make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        load_turn=load_turn,
        export_services={"fleet": services},
        game_id=GAME_ID,
        perspective=PERSPECTIVE,
    )


def _observation_job_wire(sample_turn, player_id: int) -> dict[str, object]:
    baseline = ensure_fleet_baseline_for_player(
        GAME_ID,
        PERSPECTIVE,
        sample_turn,
        player_id,
    )
    return {
        "gameId": GAME_ID,
        "perspective": PERSPECTIVE,
        "playerId": player_id,
        "materializeTurn": TURN_NUMBER,
        "turnWire": turn_info_to_json(sample_turn),
        "priorLedgerWire": None,
        "baselineLedgerWire": fleet_acquisition_ledger_to_json(baseline),
        "provenanceWire": {
            "turnEvidenceAtN": False,
            "priorLedgerAtNMinus1": False,
        },
    }


def _minimal_scores_row() -> PersistedInferenceRow:
    return PersistedInferenceRow(
        status=STATUS_EXACT,
        summary="accounting",
        solution_count=0,
        is_complete=True,
        solutions=[],
    )


def _run_parallel(worker_count: int, worker: Callable[[], None]) -> float:
    barrier = threading.Barrier(worker_count + 1)
    errors: list[BaseException] = []

    def run() -> None:
        barrier.wait()
        try:
            worker()
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(worker_count)]
    for thread in threads:
        thread.start()
    start = time.perf_counter()
    barrier.wait()
    for thread in threads:
        thread.join()
    wall = time.perf_counter() - start
    assert not errors, errors
    return wall


def test_observation_leg_does_not_touch_file_storage(tmp_path, sample_turn):
    _, counts = _counting_seeded_backend(tmp_path)
    player_id = first_player_id(sample_turn)
    job_wire = _observation_job_wire(sample_turn, player_id)

    with count_file_backend_syscalls(counts):
        result = run_fleet_observation_leg(job_wire)

    assert result.outcome == "persist"
    assert counts.protocol_counts() == {"get": 0, "put": 0, "list": 0, "delete": 0}
    assert counts.syscall_counts()["open"] == 0
    assert counts.syscall_counts()["json_load"] == 0
    assert counts.syscall_counts()["iterdir"] == 0


def test_observation_persist_and_ledger_read_call_counts(tmp_path, sample_turn):
    counting, counts = _counting_seeded_backend(tmp_path)
    persistence = FleetSnapshotPersistenceService(counting)
    ctx = _fleet_ctx(sample_turn, persistence)
    player_id = first_player_id(sample_turn)
    job_wire = _observation_job_wire(sample_turn, player_id)
    result = run_fleet_observation_leg(job_wire)
    assert result.payload is not None
    scope = ComputeScope(
        analytic_id="fleet",
        game_id=GAME_ID,
        perspective=PERSPECTIVE,
        turn=TURN_NUMBER,
        player_id=player_id,
    )

    with count_file_backend_syscalls(counts):
        FleetPersistencePolicy().persist(ctx, scope, result.payload)

    ledger_key = persistence.ledger_key(GAME_ID, PERSPECTIVE, TURN_NUMBER, player_id)
    mark_key = persistence.evidence_mark_key(GAME_ID, PERSPECTIVE, player_id)
    assert counts.protocol_counts() == {"get": 3, "put": 1, "list": 0, "delete": 0}, (
        counts.protocol_counts(),
        counts.get_keys,
        counts.list_prefixes,
    )
    assert counts.get_keys == [ledger_key, FLEET_KEY, mark_key]
    assert counts.json_load_calls == 0
    assert counts.json_dump_calls == 1
    assert counts.open_read_calls == 2
    assert counts.open_write_calls == 1
    assert counts.list_calls == 0

    counts.reset()
    with count_file_backend_syscalls(counts):
        loaded = persistence.get_ledger(GAME_ID, PERSPECTIVE, TURN_NUMBER, player_id)

    assert loaded is not None
    assert counts.protocol_counts() == {"get": 1, "put": 0, "list": 0, "delete": 0}
    assert counts.get_keys == [ledger_key]
    assert counts.json_load_calls == 0
    assert counts.open_read_calls == 0
    assert counts.open_write_calls == 0
    assert counts.iterdir_calls == 0


def test_scores_persist_and_read_call_counts(tmp_path, sample_turn):
    counting, counts = _counting_seeded_backend(tmp_path)
    persistence = InferenceRowPersistenceService(counting)
    player_id = first_player_id(sample_turn)
    row = _minimal_scores_row()
    row_key = persistence.row_store_key(GAME_ID, PERSPECTIVE, TURN_NUMBER, player_id)

    with count_file_backend_syscalls(counts):
        persistence.put_row(GAME_ID, PERSPECTIVE, TURN_NUMBER, player_id, row)

    assert counts.protocol_counts() == {"get": 0, "put": 1, "list": 0, "delete": 0}
    assert counts.json_load_calls == 0
    assert counts.json_dump_calls == 1
    assert counts.open_read_calls == 0
    assert counts.open_write_calls == 1
    assert counts.list_calls == 0
    assert row_key.endswith(f"inference_rows/{player_id}")

    counts.reset()
    with count_file_backend_syscalls(counts):
        loaded = persistence.get_row(GAME_ID, PERSPECTIVE, TURN_NUMBER, player_id)

    assert loaded is not None
    assert counts.protocol_counts() == {"get": 1, "put": 0, "list": 0, "delete": 0}
    assert counts.get_keys == [
        persistence.row_store_key(GAME_ID, PERSPECTIVE, TURN_NUMBER, player_id)
    ]
    assert counts.json_load_calls == 0
    assert counts.open_read_calls == 0
    assert counts.iterdir_calls == 0


def test_list_turns_and_analytics_prefix_call_counts(tmp_path):
    counting, counts = _counting_seeded_backend(tmp_path)
    sibling_count = len(ANALYTIC_SIBLINGS)

    with count_file_backend_syscalls(counts):
        analytics_names = counting.list(ANALYTICS_PREFIX)

    assert sorted(analytics_names) == sorted(ANALYTIC_SIBLINGS)
    assert counts.protocol_counts() == {"get": 0, "put": 0, "list": 1, "delete": 0}
    assert counts.list_prefixes == [ANALYTICS_PREFIX]
    assert counts.iterdir_calls == 1
    assert counts.json_load_calls == 0
    assert counts.is_dir_calls == 1 + sibling_count
    assert counts.is_file_calls == sibling_count

    counts.reset()
    with count_file_backend_syscalls(counts):
        turn_names = counting.list(TURNS_PREFIX)

    assert set(turn_names) == {"110", "111", "112"}
    assert counts.protocol_counts() == {"get": 0, "put": 0, "list": 1, "delete": 0}
    assert counts.list_prefixes == [TURNS_PREFIX]
    assert counts.iterdir_calls == 1
    assert counts.json_load_calls == 0
    # 3 turn json files + 3 per-turn analytics directories.
    assert counts.is_dir_calls == 1 + 6
    assert counts.is_file_calls == 3


def test_job_wire_build_skips_disk_when_dependency_outputs_has_final_prior(tmp_path, sample_turn):
    """Final prior on DependencyOutputs is enough; do not re-get the fleet document."""
    counting, counts = _counting_seeded_backend(tmp_path)
    persistence = FleetSnapshotPersistenceService(counting)
    player_id = first_player_id(sample_turn)
    prior_turn = TURN_NUMBER - 1
    prior_ledger = ensure_fleet_baseline_for_player(
        GAME_ID,
        PERSPECTIVE,
        sample_turn,
        player_id,
    )
    persisted = PersistedFleetLedger(
        ledger=prior_ledger,
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
    )
    persistence.put_ledger(GAME_ID, PERSPECTIVE, prior_turn, player_id, persisted)
    stored = persistence.get_ledger(GAME_ID, PERSPECTIVE, prior_turn, player_id)
    assert stored is not None
    counts.reset()

    prior_scope = ComputeScope(
        analytic_id="fleet",
        game_id=GAME_ID,
        perspective=PERSPECTIVE,
        turn=prior_turn,
        player_id=player_id,
    )
    scope = ComputeScope(
        analytic_id="fleet",
        game_id=GAME_ID,
        perspective=PERSPECTIVE,
        turn=TURN_NUMBER,
        player_id=player_id,
    )
    outputs = DependencyOutputs()
    outputs.put(
        prior_scope,
        {"persistedLedgerWire": persisted_fleet_ledger_to_json(stored)},
    )
    ctx = _fleet_ctx(sample_turn, persistence)

    with count_file_backend_syscalls(counts):
        wire = build_fleet_materialization_leg_job_wire(
            scope,
            dependency_outputs=outputs,
            ctx=ctx,
        )

    assert wire["priorLedgerWire"] is not None
    assert counts.list_calls == 0
    assert counts.put_calls == 0
    assert counts.get_calls == 0
    assert counts.get_keys == []
    assert counts.json_load_calls == 0


def test_scores_resolve_prior_skips_disk_when_dependency_outputs_has_final_prior(
    tmp_path, sample_turn
):
    """Final prior on DependencyOutputs is enough; do not re-get the fleet document."""
    counting, counts = _counting_seeded_backend(tmp_path)
    persistence = FleetSnapshotPersistenceService(counting)
    player_id = first_player_id(sample_turn)
    prior_turn = TURN_NUMBER - 1
    prior_ledger = ensure_fleet_baseline_for_player(
        GAME_ID,
        PERSPECTIVE,
        sample_turn,
        player_id,
    )
    persisted = PersistedFleetLedger(
        ledger=prior_ledger,
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
    )
    persistence.put_ledger(GAME_ID, PERSPECTIVE, prior_turn, player_id, persisted)
    stored = persistence.get_ledger(GAME_ID, PERSPECTIVE, prior_turn, player_id)
    assert stored is not None
    counts.reset()

    prior_scope = ComputeScope(
        analytic_id="fleet",
        game_id=GAME_ID,
        perspective=PERSPECTIVE,
        turn=prior_turn,
        player_id=player_id,
    )
    outputs = DependencyOutputs()
    outputs.put(
        prior_scope,
        {"persistedLedgerWire": persisted_fleet_ledger_to_json(stored)},
    )
    ctx = _fleet_ctx(sample_turn, persistence)

    with count_file_backend_syscalls(counts):
        resolution = resolve_prior_fleet_for_scores(
            ctx,
            game_id=GAME_ID,
            perspective=PERSPECTIVE,
            turn_number=TURN_NUMBER,
            player_id=player_id,
            turn=sample_turn,
            dependency_outputs=outputs,
            overlay_ensure=False,
        )

    prior_fleet_key = persistence.document_key(GAME_ID, PERSPECTIVE, prior_turn)
    assert resolution.input_status == "applied"
    assert resolution.overlay is not None
    assert counts.list_calls == 0
    assert counts.put_calls == 0
    assert counts.get_calls == 0
    assert prior_fleet_key not in counts.get_keys
    assert counts.get_keys == []
    assert counts.json_load_calls == 0


def _file_mix(backend: FileStorageBackend) -> None:
    for _ in range(FILE_MIX_ITERS):
        backend.get(TURN_KEY)
        backend.list(ANALYTICS_PREFIX)
        backend.get(FLEET_KEY)


def test_file_backend_get_list_mix_does_not_scale_like_sleep_control(tmp_path):
    backend = _file_backend(tmp_path)
    # Warm the mix before timing so 1-thread and 8-thread walls share a hot cache.
    _file_mix(backend)

    single_file_wall = _run_parallel(1, lambda: _file_mix(backend))
    eight_file_wall = _run_parallel(WORKER_COUNT, lambda: _file_mix(backend))
    file_throughput_ratio = (WORKER_COUNT * single_file_wall) / eight_file_wall

    single_sleep_wall = _run_parallel(1, lambda: time.sleep(SLEEP_SECONDS))
    eight_sleep_wall = _run_parallel(WORKER_COUNT, lambda: time.sleep(SLEEP_SECONDS))
    sleep_throughput_ratio = (WORKER_COUNT * single_sleep_wall) / eight_sleep_wall

    assert sleep_throughput_ratio >= SLEEP_MIN_THROUGHPUT_RATIO, (
        "sleep control must overlap "
        f"(ratio={sleep_throughput_ratio:.2f}, single={single_sleep_wall:.3f}s, "
        f"eight={eight_sleep_wall:.3f}s)"
    )
    assert file_throughput_ratio <= FILE_MAX_THROUGHPUT_RATIO, (
        "file-backend get+list mix must not scale toward 8x "
        f"(ratio={file_throughput_ratio:.2f}, single={single_file_wall:.3f}s, "
        f"eight={eight_file_wall:.3f}s)"
    )
