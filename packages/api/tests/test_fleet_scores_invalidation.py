"""Fleet ledger persist -> scores inference invalidation coupling (#182, #184)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from api.analytics.export_context import make_analytic_query_context
from api.analytics.fleet.chain import get_or_materialize_fleet_snapshot
from api.analytics.fleet.compute_orchestration import FleetPersistencePolicy
from api.analytics.fleet.compute_services import FleetComputeServices
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.serialization import persisted_fleet_ledger_to_json
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetMaterializationProvenance,
    PersistedFleetLedger,
)
from api.analytics.options import TurnAnalyticsOptions
from api.compute.scope import ComputeScope
from api.serialization.turn import turn_info_from_json
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend

from tests.test_fleet_persistence import (
    _inference_materialization_for_fleet,
    _put_provenance_final_snapshot,
    _seed_scores_rows_for_all_players,
)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"
API_ROOT = Path(__file__).resolve().parent.parent / "api"


def _fake_orchestrator_with_nodes(nodes: dict) -> object:
    """Minimal orchestrator stub that implements adapter peek APIs over ``nodes``."""
    from api.compute.orchestrator import ScopeNodeView

    class FakeOrchestrator:
        def __init__(self) -> None:
            self.nodes = nodes

        def peek_scope_view(self, scope: ComputeScope) -> ScopeNodeView | None:
            node = self.nodes.get(scope)
            if node is None:
                return None
            return ScopeNodeView(
                state=node.state,
                step_index=node.step_index,
                dependency_scopes=frozenset(node.dependency_scopes),
                result_wire=node.result_wire,
            )

    return FakeOrchestrator()


def _bind_own_dag_fleet_persist(
    scheduler,
    *,
    scores_state: str,
    depends_on_fleet: bool,
    ledger_materialization_version: int | None = None,
):
    """Install stream binding + peek orchestrator for own-DAG fleet persist cases."""
    from api.analytics.fleet.constants import FLEET_MATERIALIZATION_VERSION
    from api.analytics.fleet.ledger_persisted_event import FleetLedgerPersistedEvent
    from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.orchestrator import ComputeNodeRun

    if ledger_materialization_version is None:
        ledger_materialization_version = FLEET_MATERIALIZATION_VERSION
    scope = InferenceStreamScope(game_id=628580, perspective=1, turn_number=112)
    stream_token = scheduler.begin_scope(scope)
    scores_scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=112,
        player_id=8,
    )
    fleet_scope = ComputeScope(
        analytic_id="fleet",
        game_id=628580,
        perspective=1,
        turn=111,
        player_id=8,
    )
    persisted = PersistedFleetLedger(
        ledger=FleetAcquisitionLedger(player_id=8),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
        materialization_version=ledger_materialization_version,
    )
    scheduler._stream_bindings[stream_token] = type(
        "FakeBinding",
        (),
        {
            "orchestrator": _fake_orchestrator_with_nodes(
                {
                    scores_scope: ComputeNodeRun(
                        scope=scores_scope,
                        dependency_scopes=(fleet_scope,) if depends_on_fleet else (),
                        state=scores_state,
                    ),
                    fleet_scope: ComputeNodeRun(
                        scope=fleet_scope,
                        dependency_scopes=(),
                        state="complete",
                        result_wire={
                            "persistedLedgerWire": persisted_fleet_ledger_to_json(persisted),
                        },
                    ),
                }
            ),
            "query_context": object(),
        },
    )()
    event = FleetLedgerPersistedEvent(
        game_id=628580,
        perspective=1,
        fleet_turn=111,
        player_id=8,
        materialization_version=FLEET_MATERIALIZATION_VERSION,
    )
    return scope, event


@pytest.fixture
def memory_backend():
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        backend.put("games/628580/info", json.load(handle))
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        turn_rst = json.load(handle)
        backend.put("games/628580/1/turns/111", turn_rst)
        turn_110 = copy.deepcopy(turn_rst)
        turn_110["settings"]["turn"] = 110
        turn_110["game"]["turn"] = 110
        backend.put("games/628580/1/turns/110", turn_110)
        turn_112 = copy.deepcopy(turn_rst)
        turn_112["settings"]["turn"] = 112
        turn_112["game"]["turn"] = 112
        backend.put("games/628580/1/turns/112", turn_112)
    return backend


@pytest.fixture
def persistence(memory_backend):
    return FleetSnapshotPersistenceService(memory_backend)


@pytest.fixture
def load_turn(memory_backend):
    def _load(turn_number: int):
        key = f"games/628580/1/turns/{turn_number}"
        try:
            data = memory_backend.get(key)
        except Exception:
            return None
        if data is None:
            return None
        return turn_info_from_json(data)

    return _load


def test_materialize_chain_does_not_invoke_on_snapshot_persisted(
    persistence,
    load_turn,
    memory_backend,
):
    """Per-player gap-fill must use ledger notification only, not roster snapshot callback."""
    turn_111 = load_turn(111)
    assert turn_111 is not None
    turn_110 = load_turn(110)
    assert turn_110 is not None
    _put_provenance_final_snapshot(persistence, 628580, 1, turn_110)

    inference_persistence, inference_materialization = _inference_materialization_for_fleet(
        memory_backend,
        load_turn,
    )
    _seed_scores_rows_for_all_players(inference_persistence, turn_111)

    snapshot_callback_turns: list[int] = []
    ledger_callback_events: list[tuple[int, int]] = []
    persistence.on_snapshot_persisted = lambda _g, _p, turn_number: snapshot_callback_turns.append(
        turn_number
    )

    def on_ledger_persisted(event) -> None:
        ledger_callback_events.append((event.fleet_turn, event.player_id))

    persistence.on_ledger_persisted = on_ledger_persisted

    snapshot = get_or_materialize_fleet_snapshot(
        persistence,
        628580,
        1,
        turn_111,
        load_turn=load_turn,
        inference_materialization=inference_materialization,
    )

    assert snapshot.turn == 111
    assert snapshot_callback_turns == []
    assert ledger_callback_events
    assert all(turn_number == 111 for turn_number, _ in ledger_callback_events)


def test_single_player_hot_paths_do_not_reference_on_snapshot_persisted():
    """Guard: chain materialize paths stay on per-player ledger notify."""
    guarded_modules = (API_ROOT / "analytics" / "fleet" / "chain.py",)
    for module_path in guarded_modules:
        source = module_path.read_text(encoding="utf-8")
        assert "on_snapshot_persisted" not in source, (
            f"{module_path.name} must not wire roster snapshot notification"
        )
    assert not (API_ROOT / "analytics" / "fleet" / "gap_fill_deferred_notifications.py").exists()


def test_leaf_materialize_notifies_immediately_on_each_final_persist(
    persistence,
    load_turn,
    memory_backend,
):
    """Leaf put_ledger fires on_ledger_persisted immediately (N1'; no end-of-chain batch)."""
    from api.analytics.turn_roster import iter_turn_players

    turn_111 = load_turn(111)
    assert turn_111 is not None
    turn_110 = load_turn(110)
    assert turn_110 is not None
    _put_provenance_final_snapshot(persistence, 628580, 1, turn_110)

    inference_persistence, inference_materialization = _inference_materialization_for_fleet(
        memory_backend,
        load_turn,
    )
    _seed_scores_rows_for_all_players(inference_persistence, turn_111)

    callback_events: list[tuple[int, int]] = []
    notify_counts_during_put: list[int] = []
    original_put_ledger = persistence.put_ledger

    def counting_put_ledger(*args, **kwargs):
        before = len(callback_events)
        result = original_put_ledger(*args, **kwargs)
        notify_counts_during_put.append(len(callback_events) - before)
        return result

    persistence.on_ledger_persisted = lambda event: callback_events.append(
        (event.fleet_turn, event.player_id)
    )
    persistence.put_ledger = counting_put_ledger  # type: ignore[method-assign]

    snapshot = get_or_materialize_fleet_snapshot(
        persistence,
        628580,
        1,
        turn_111,
        load_turn=load_turn,
        inference_materialization=inference_materialization,
    )

    assert snapshot.turn == 111
    roster_size = len(list(iter_turn_players(turn_111)))
    assert roster_size > 1
    assert len(callback_events) == roster_size
    assert all(turn_number == 111 for turn_number, _ in callback_events)
    # Each put that becomes final notifies inside put_ledger, not in a later flush.
    assert sum(notify_counts_during_put) == roster_size


def test_leaf_final_persist_invalidates_scores_at_next_turn(
    persistence,
    load_turn,
    memory_backend,
):
    """Single-turn leaf final fleet@T invalidates scores@(T+1) immediately on put."""
    from api.analytics.turn_roster import iter_turn_players

    inference_persistence, inference_materialization = _inference_materialization_for_fleet(
        memory_backend,
        load_turn,
    )
    invalidation = InferenceInvalidationService(
        inference_persistence,
        fleet_persistence=persistence,
    )
    invalidation.wire_scores_invalidation_to_fleet_persistence()

    turn_111 = load_turn(111)
    assert turn_111 is not None
    turn_110 = load_turn(110)
    assert turn_110 is not None
    turn_112 = load_turn(112)
    assert turn_112 is not None
    _put_provenance_final_snapshot(persistence, 628580, 1, turn_110)
    _seed_scores_rows_for_all_players(inference_persistence, turn_111)
    _seed_scores_rows_for_all_players(inference_persistence, turn_112)

    snapshot = get_or_materialize_fleet_snapshot(
        persistence,
        628580,
        1,
        turn_111,
        load_turn=load_turn,
        inference_materialization=inference_materialization,
    )

    assert snapshot.turn == 111
    for player in iter_turn_players(turn_112):
        assert inference_persistence.get_row(628580, 1, 112, player.id) is None


def test_fleet_ledger_persisted_invalidates_scores_row_for_player_only(
    persistence,
    load_turn,
    memory_backend,
    monkeypatch,
):
    from api.analytics.turn_roster import iter_turn_players

    inference_persistence, _ = _inference_materialization_for_fleet(memory_backend, load_turn)
    turn_112 = load_turn(112)
    assert turn_112 is not None
    players = list(iter_turn_players(turn_112))
    player_p = players[0].id
    player_q = players[1].id
    _seed_scores_rows_for_all_players(inference_persistence, turn_112)

    rescheduled_players: list[int] = []
    all_rescheduled: list[None] = []

    def spy_reschedule_row(_scope, player_id, **_kwargs):
        rescheduled_players.append(player_id)

    def spy_reschedule_all(_scope, **_kwargs):
        all_rescheduled.append(None)

    monkeypatch.setattr(
        "api.services.inference_invalidation_service.reschedule_inference_row",
        spy_reschedule_row,
    )
    monkeypatch.setattr(
        "api.services.inference_invalidation_service.reschedule_all_inference_rows",
        spy_reschedule_all,
    )

    invalidation = InferenceInvalidationService(
        inference_persistence,
        fleet_persistence=persistence,
    )
    invalidation.wire_scores_invalidation_to_fleet_persistence()

    from api.analytics.fleet.constants import FLEET_MATERIALIZATION_VERSION
    from api.analytics.fleet.ledger_persisted_event import FleetLedgerPersistedEvent

    invalidation.on_fleet_ledger_persisted(
        FleetLedgerPersistedEvent(
            game_id=628580,
            perspective=1,
            fleet_turn=111,
            player_id=player_p,
            materialization_version=FLEET_MATERIALIZATION_VERSION,
        )
    )

    assert inference_persistence.get_row(628580, 1, 112, player_p) is None
    assert inference_persistence.get_row(628580, 1, 112, player_q) is not None
    assert rescheduled_players == [player_p]


def test_fleet_ledger_persist_skips_reschedule_when_stream_dep_delivers_matching_ledger(
    persistence,
    memory_backend,
    monkeypatch,
):
    """Own-DAG elision: skip wipe and reschedule when scores waits on matching fleet."""
    from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
    from api.analytics.military_score_inference.solver import STATUS_EXACT
    from api.serialization.inference_row_persistence import PersistedInferenceRow

    inference_persistence = InferenceRowPersistenceService(memory_backend)
    scheduler = InferenceRowScheduler(worker_count=0)
    _scope, event = _bind_own_dag_fleet_persist(
        scheduler,
        scores_state="waiting_deps",
        depends_on_fleet=True,
    )

    rescheduled_players: list[int] = []
    monkeypatch.setattr(
        "api.services.inference_invalidation_service.reschedule_inference_row",
        lambda _scope, player_id: rescheduled_players.append(player_id) or True,
    )

    # Seed a durable scores row so on_fleet_ledger_persisted would wipe it if not elided.
    inference_persistence.put_row(
        628580,
        1,
        112,
        8,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="cached-8",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
        notify=False,
    )
    assert inference_persistence.get_row(628580, 1, 112, 8) is not None

    invalidation = InferenceInvalidationService(
        inference_persistence,
        scheduler=scheduler,
        fleet_persistence=persistence,
    )
    invalidation.on_fleet_ledger_persisted(event)

    assert rescheduled_players == []
    assert inference_persistence.get_row(628580, 1, 112, 8) is not None


def test_fleet_ledger_persist_skips_reschedule_for_cold_own_dag_without_stream(
    monkeypatch,
):
    """Cold ensure DAG: own-DAG elision via process orchestrator with no stream binding."""
    from api.analytics.fleet.constants import FLEET_MATERIALIZATION_VERSION
    from api.analytics.fleet.ledger_persisted_event import FleetLedgerPersistedEvent
    from api.analytics.fleet.serialization import persisted_fleet_ledger_to_json
    from api.analytics.fleet.types import FleetAcquisitionLedger, FleetMaterializationProvenance
    from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
    from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.orchestrator import ComputeNodeRun

    scheduler = InferenceRowScheduler(worker_count=0)
    scope = InferenceStreamScope(game_id=628580, perspective=1, turn_number=112)
    # No begin_scope / stream binding -- cold export-ensure path.
    scores_scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=112,
        player_id=8,
    )
    fleet_scope = ComputeScope(
        analytic_id="fleet",
        game_id=628580,
        perspective=1,
        turn=111,
        player_id=8,
    )
    persisted = PersistedFleetLedger(
        ledger=FleetAcquisitionLedger(player_id=8),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
        materialization_version=FLEET_MATERIALIZATION_VERSION,
    )
    process_orchestrator = _fake_orchestrator_with_nodes(
        {
            scores_scope: ComputeNodeRun(
                scope=scores_scope,
                dependency_scopes=(fleet_scope,),
                state="waiting_deps",
            ),
            fleet_scope: ComputeNodeRun(
                scope=fleet_scope,
                dependency_scopes=(),
                state="complete",
                result_wire={
                    "persistedLedgerWire": persisted_fleet_ledger_to_json(persisted),
                },
            ),
        }
    )
    monkeypatch.setattr(
        "api.compute.runtime.get_compute_orchestrator",
        lambda: process_orchestrator,
    )

    event = FleetLedgerPersistedEvent(
        game_id=628580,
        perspective=1,
        fleet_turn=111,
        player_id=8,
        materialization_version=FLEET_MATERIALIZATION_VERSION,
    )
    wipe_calls = 0

    def _count_wipe() -> None:
        nonlocal wipe_calls
        wipe_calls += 1

    assert (
        scheduler.should_reschedule_scores_row_after_fleet_persist(
            scope,
            event,
            invalidate_row=_count_wipe,
        )
        is False
    )
    assert wipe_calls == 0


def test_fleet_ledger_persist_reschedules_for_external_persist_while_waiting_on_fleet(
    memory_backend,
):
    from api.analytics.fleet.constants import FLEET_MATERIALIZATION_VERSION
    from api.analytics.fleet.ledger_persisted_event import FleetLedgerPersistedEvent
    from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
    from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.orchestrator import ComputeNodeRun

    scheduler = InferenceRowScheduler(worker_count=0)
    scope = InferenceStreamScope(game_id=628580, perspective=1, turn_number=112)
    stream_token = scheduler.begin_scope(scope)
    scores_scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=112,
        player_id=8,
    )
    fleet_scope = ComputeScope(
        analytic_id="fleet",
        game_id=628580,
        perspective=1,
        turn=111,
        player_id=8,
    )
    scheduler._stream_bindings[stream_token] = type(
        "FakeBinding",
        (),
        {
            "orchestrator": _fake_orchestrator_with_nodes(
                {
                    scores_scope: ComputeNodeRun(
                        scope=scores_scope,
                        dependency_scopes=(fleet_scope,),
                        state="waiting_deps",
                    ),
                }
            ),
            "query_context": object(),
        },
    )()

    event = FleetLedgerPersistedEvent(
        game_id=628580,
        perspective=1,
        fleet_turn=111,
        player_id=8,
        materialization_version=FLEET_MATERIALIZATION_VERSION,
    )
    wipe_calls = 0

    def _count_wipe() -> None:
        nonlocal wipe_calls
        wipe_calls += 1

    assert (
        scheduler.should_reschedule_scores_row_after_fleet_persist(
            scope,
            event,
            invalidate_row=_count_wipe,
        )
        is True
    )
    assert wipe_calls == 1


@pytest.mark.parametrize(
    ("scores_state", "depends_on_fleet", "expect_reschedule"),
    (
        ("waiting_deps", True, False),
        ("ready", True, False),
        ("running", True, False),
        ("parked", True, False),
        ("running", False, True),
    ),
)
def test_fleet_ledger_persist_own_dag_elision(
    scores_state,
    depends_on_fleet,
    expect_reschedule,
):
    """Own-DAG elision skips wipe when non-terminal scores depend on this fleet persist.

    Matching completed fleet@(N-1) must not cancel in-flight scores@N that already
    depends on that fleet node. In-flight scores with no edge to this fleet persist
    is still external and must wipe+reschedule.
    """
    from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler

    scheduler = InferenceRowScheduler(worker_count=0)
    scope, event = _bind_own_dag_fleet_persist(
        scheduler,
        scores_state=scores_state,
        depends_on_fleet=depends_on_fleet,
    )
    wipe_calls = 0

    def _count_wipe() -> None:
        nonlocal wipe_calls
        wipe_calls += 1

    assert (
        scheduler.should_reschedule_scores_row_after_fleet_persist(
            scope,
            event,
            invalidate_row=_count_wipe,
        )
        is expect_reschedule
    )
    assert wipe_calls == (1 if expect_reschedule else 0)


def test_fleet_ledger_persist_reschedules_when_stream_fleet_version_differs():
    from api.analytics.fleet.constants import FLEET_MATERIALIZATION_VERSION
    from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler

    scheduler = InferenceRowScheduler(worker_count=0)
    scope, event = _bind_own_dag_fleet_persist(
        scheduler,
        scores_state="waiting_deps",
        depends_on_fleet=True,
        ledger_materialization_version=FLEET_MATERIALIZATION_VERSION - 1,
    )
    assert (
        scheduler.should_reschedule_scores_row_after_fleet_persist(
            scope,
            event,
            invalidate_row=lambda: None,
        )
        is True
    )


def test_fleet_ledger_persist_skips_when_stream_wire_lacks_version_stamp(
    memory_backend,
):
    """Same-orchestrator dep delivery may omit version on result wire until storage stamp."""
    from api.analytics.fleet.constants import FLEET_MATERIALIZATION_VERSION
    from api.analytics.fleet.ledger_persisted_event import FleetLedgerPersistedEvent
    from api.analytics.fleet.serialization import persisted_fleet_ledger_to_json
    from api.analytics.fleet.types import FleetAcquisitionLedger, FleetMaterializationProvenance
    from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
    from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.orchestrator import ComputeNodeRun

    scheduler = InferenceRowScheduler(worker_count=0)
    scope = InferenceStreamScope(game_id=628580, perspective=1, turn_number=112)
    stream_token = scheduler.begin_scope(scope)
    query_context = object()
    scores_scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=112,
        player_id=8,
    )
    fleet_scope = ComputeScope(
        analytic_id="fleet",
        game_id=628580,
        perspective=1,
        turn=111,
        player_id=8,
    )
    unstamped = PersistedFleetLedger(
        ledger=FleetAcquisitionLedger(player_id=8),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
        materialization_version=0,
    )
    wire = persisted_fleet_ledger_to_json(unstamped)
    del wire["materializationVersion"]
    scheduler._stream_bindings[stream_token] = type(
        "FakeBinding",
        (),
        {
            "orchestrator": _fake_orchestrator_with_nodes(
                {
                    scores_scope: ComputeNodeRun(
                        scope=scores_scope,
                        dependency_scopes=(fleet_scope,),
                        state="waiting_deps",
                    ),
                    fleet_scope: ComputeNodeRun(
                        scope=fleet_scope,
                        dependency_scopes=(),
                        state="complete",
                        result_wire={"persistedLedgerWire": wire},
                    ),
                }
            ),
            "query_context": query_context,
        },
    )()

    event = FleetLedgerPersistedEvent(
        game_id=628580,
        perspective=1,
        fleet_turn=111,
        player_id=8,
        materialization_version=FLEET_MATERIALIZATION_VERSION,
    )
    assert (
        scheduler.should_reschedule_scores_row_after_fleet_persist(
            scope,
            event,
            invalidate_row=lambda: None,
        )
        is False
    )


def test_fleet_ledger_persist_reschedules_for_external_persist_while_stream_fleet_dep_in_flight(
    memory_backend,
):
    """In-DAG fleet work skips external persist reschedule while the dep is non-terminal."""
    from api.analytics.fleet.constants import FLEET_MATERIALIZATION_VERSION
    from api.analytics.fleet.ledger_persisted_event import FleetLedgerPersistedEvent
    from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
    from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.orchestrator import ComputeNodeRun

    scheduler = InferenceRowScheduler(worker_count=0)
    scope = InferenceStreamScope(game_id=628580, perspective=1, turn_number=112)
    stream_token = scheduler.begin_scope(scope)
    scores_scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=112,
        player_id=8,
    )
    fleet_scope = ComputeScope(
        analytic_id="fleet",
        game_id=628580,
        perspective=1,
        turn=111,
        player_id=8,
    )
    scheduler._stream_bindings[stream_token] = type(
        "FakeBinding",
        (),
        {
            "orchestrator": _fake_orchestrator_with_nodes(
                {
                    scores_scope: ComputeNodeRun(
                        scope=scores_scope,
                        dependency_scopes=(fleet_scope,),
                        state="waiting_deps",
                    ),
                    fleet_scope: ComputeNodeRun(
                        scope=fleet_scope,
                        dependency_scopes=(),
                        state="running",
                    ),
                }
            ),
            "query_context": object(),
        },
    )()

    event = FleetLedgerPersistedEvent(
        game_id=628580,
        perspective=1,
        fleet_turn=111,
        player_id=8,
        materialization_version=FLEET_MATERIALIZATION_VERSION,
    )
    assert (
        scheduler.should_reschedule_scores_row_after_fleet_persist(
            scope,
            event,
            invalidate_row=lambda: None,
        )
        is True
    )


def test_orchestrator_fleet_persist_notifies_scores_invalidation(
    persistence,
    load_turn,
    memory_backend,
    monkeypatch,
):
    from api.analytics.turn_roster import iter_turn_players

    inference_persistence = InferenceRowPersistenceService(memory_backend)
    turn_112 = load_turn(112)
    assert turn_112 is not None
    players = list(iter_turn_players(turn_112))
    player_p = players[0].id
    player_q = players[1].id
    _seed_scores_rows_for_all_players(inference_persistence, turn_112)

    rescheduled_players: list[int] = []
    monkeypatch.setattr(
        "api.services.inference_invalidation_service.reschedule_inference_row",
        lambda _scope, player_id: rescheduled_players.append(player_id),
    )

    invalidation = InferenceInvalidationService(
        inference_persistence,
        fleet_persistence=persistence,
    )
    invalidation.wire_scores_invalidation_to_fleet_persistence()

    turn_111 = load_turn(111)
    assert turn_111 is not None
    ctx = make_analytic_query_context(
        turn_111,
        TurnAnalyticsOptions(),
        game_id=628580,
        perspective=1,
        load_turn=load_turn,
        export_services={
            "fleet": FleetComputeServices(
                persistence=persistence,
                game_id=628580,
                perspective=1,
                load_turn=load_turn,
            ),
        },
    )
    persisted = PersistedFleetLedger(
        ledger=FleetAcquisitionLedger(player_id=player_p),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
    )

    notification = FleetPersistencePolicy().persist(
        ctx,
        ComputeScope(
            analytic_id="fleet",
            game_id=628580,
            perspective=1,
            turn=111,
            player_id=player_p,
        ),
        {"persistedLedgerWire": persisted_fleet_ledger_to_json(persisted)},
    )
    assert notification is not None
    notification()

    assert inference_persistence.get_row(628580, 1, 112, player_p) is None
    assert inference_persistence.get_row(628580, 1, 112, player_q) is not None
    assert rescheduled_players == [player_p]


def test_scores_evidence_update_wakes_fleet_even_without_ledger_to_clear(
    persistence,
    monkeypatch,
):
    """Refused fleet persist leaves no ledger; scores re-close must still force_fresh fleet@N."""
    rescheduled: list[tuple[int, int]] = []

    def spy_reschedule(scope, player_id):
        rescheduled.append((scope.turn_number, player_id))
        return True

    monkeypatch.setattr(
        "api.services.inference_invalidation_service.reschedule_fleet_table_player",
        spy_reschedule,
    )
    inference_persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    invalidation = InferenceInvalidationService(
        inference_persistence,
        fleet_persistence=persistence,
    )
    gen_before = persistence.player_invalidation_generation(628580, 1, 8)
    turn_gen_before = persistence.turn_invalidation_generation(628580, 1, 8, 4)

    woken = invalidation.on_inference_evidence_updated(628580, 1, 4, 8)

    assert woken == {4}
    assert rescheduled == [(4, 8)]
    assert persistence.player_invalidation_generation(628580, 1, 8) == gen_before + 1
    assert persistence.turn_invalidation_generation(628580, 1, 8, 4) == turn_gen_before + 1
    assert persistence.turn_invalidation_generation(628580, 1, 8, 5) == 0


def test_scores_evidence_update_force_freshes_fleet_when_stream_closed(
    persistence,
    monkeypatch,
):
    """Closed-stream scores wipe must force_fresh fleet, not only stream reschedule."""
    from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID

    stream_calls: list[tuple[int, int]] = []
    woken: list[ComputeScope] = []

    def spy_reschedule(scope, player_id):
        stream_calls.append((scope.turn_number, player_id))
        return False

    def spy_wake(scope, **_kwargs):
        woken.append(scope)
        return True

    monkeypatch.setattr(
        "api.services.inference_invalidation_service.reschedule_fleet_table_player",
        spy_reschedule,
    )
    monkeypatch.setattr(
        "api.services.inference_invalidation_service.wake_fleet_scope",
        spy_wake,
    )
    inference_persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    invalidation = InferenceInvalidationService(
        inference_persistence,
        fleet_persistence=persistence,
    )

    woken_turns = invalidation.on_inference_evidence_updated(628580, 1, 4, 8)

    assert woken_turns == {4}
    assert stream_calls == [(4, 8)]
    assert len(woken) == 1
    assert woken[0] == ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=4,
        player_id=8,
    )


def test_waiting_deps_fleet_leaves_dependents_waiting_failed_fleet_cascades(sample_turn):
    """Persist recovery leaves fleet waiting_deps; only a real failed fleet cascades.

    PersistDeferredError recovery leaves the fleet node ``waiting_deps`` (not
    ``failed``), so scores dependents stay ``waiting_deps``. A normal fleet
    failure cascades like any other failed dependency -- no PersistDeferredError
    cascade-skip special case.
    """
    from api.analytics.fleet import REGISTRATION as FLEET_REGISTRATION
    from api.analytics.scores import REGISTRATION as SCORES_REGISTRATION
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator
    from api.compute.registry import build_compute_registry

    registry = build_compute_registry((FLEET_REGISTRATION, SCORES_REGISTRATION))
    make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        export_services={},
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
    )
    orchestrator = ComputeOrchestrator(compute_registry=registry)

    fleet_scope = ComputeScope(
        analytic_id="fleet",
        game_id=628580,
        perspective=1,
        turn=4,
        player_id=2,
    )
    scores_scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=5,
        player_id=2,
    )

    waiting_fleet = ComputeNodeRun(
        scope=fleet_scope,
        dependency_scopes=(),
        state="waiting_deps",
    )
    waiting_scores = ComputeNodeRun(
        scope=scores_scope,
        dependency_scopes=(fleet_scope,),
        state="waiting_deps",
    )
    orchestrator._nodes[fleet_scope] = waiting_fleet
    orchestrator._nodes[scores_scope] = waiting_scores

    with orchestrator._condition:
        orchestrator._refresh_node_readiness(waiting_scores)

    assert waiting_scores.state == "waiting_deps"
    assert waiting_scores.error is None

    fleet_failure = RuntimeError("fleet step failed")
    failed_fleet = ComputeNodeRun(
        scope=fleet_scope,
        dependency_scopes=(),
        state="failed",
        error=fleet_failure,
    )
    cascade_scores = ComputeNodeRun(
        scope=scores_scope,
        dependency_scopes=(fleet_scope,),
        state="waiting_deps",
    )
    orchestrator._nodes[fleet_scope] = failed_fleet
    orchestrator._nodes[scores_scope] = cascade_scores

    with orchestrator._condition:
        orchestrator._refresh_node_readiness(cascade_scores)

    assert cascade_scores.state == "failed"
    assert cascade_scores.error is fleet_failure
