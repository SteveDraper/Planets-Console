"""Tests for TurnAnalyticService."""

import json
from pathlib import Path

import pytest
from api.errors import NotFoundError
from api.services.stack import build_service_stack
from api.storage.memory_asset import MemoryAssetBackend

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def analytics_service():
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        backend.put("games/628580/info", json.load(f))
    with open(ASSETS_DIR / "turn_sample.json") as f:
        backend.put("games/628580/1/turns/111", json.load(f))
    _, _, _, _, analytics, _ = build_service_stack(backend)
    return analytics


class TestTurnAnalytics:
    def test_base_map_returns_planet_nodes(self, analytics_service):
        data = analytics_service.get_turn_analytics(628580, 1, 111, "base-map")
        assert data["analyticId"] == "base-map"
        assert isinstance(data["nodes"], list)
        assert len(data["nodes"]) > 0
        first = data["nodes"][0]
        assert first["id"].startswith("p")
        assert "x" in first and "y" in first
        assert "planet" in first
        assert isinstance(first["planet"], dict)
        assert first["planet"]["id"] == 1
        assert "ownerName" in first
        assert "normalWellCells" in first
        assert isinstance(first["normalWellCells"], list)
        assert len(first["normalWellCells"]) == 29
        assert data["edges"] == []

    def test_base_map_not_found_turn_raises(self, analytics_service):
        with pytest.raises(NotFoundError):
            analytics_service.get_turn_analytics(628580, 1, 999, "base-map")

    def test_scores_returns_score_rows_with_current_values_and_changes(self, analytics_service):
        data = analytics_service.get_turn_analytics(628580, 1, 111, "scores")
        assert data["analyticId"] == "scores"
        assert len(data["rows"]) == 3
        first = data["rows"][0]
        assert first["playerId"] == 8
        assert first["racePlayer"] == "koshling"
        assert first["planets"] == {"value": 171, "change": -4}
        assert first["starbases"] == {"value": 121, "change": -2}
        assert first["warShips"] == {"value": 130, "change": 1}
        assert first["freighters"] == {"value": 26, "change": 0}
        assert first["military"] == {"value": 2509092, "change": -53869}
        assert first["priorityPoints"] == {"value": 217, "change": 54}

    def test_scores_table_does_not_submit_orchestrator(self, analytics_service, monkeypatch):
        def fail_orchestrator(**_kwargs):
            raise AssertionError("scores REST must not submit table/map compute")

        monkeypatch.setattr(
            "api.compute.runtime.get_compute_orchestrator",
            fail_orchestrator,
        )
        data = analytics_service.get_turn_analytics(628580, 1, 111, "scores")
        assert data["analyticId"] == "scores"
        assert len(data["rows"]) == 3

    def test_base_map_does_not_submit_orchestrator(self, analytics_service, monkeypatch):
        def fail_orchestrator(**_kwargs):
            raise AssertionError("base-map REST must not submit table/map compute")

        monkeypatch.setattr(
            "api.compute.runtime.get_compute_orchestrator",
            fail_orchestrator,
        )
        data = analytics_service.get_turn_analytics(628580, 1, 111, "base-map")
        assert data["analyticId"] == "base-map"

    def test_scores_inference_stream_wrapper_forwards_export_services(
        self,
        sample_turn,
        monkeypatch,
    ):
        from api.analytics import scores
        from api.analytics.military_score_inference import inference_stream_rows

        forwarded: dict[str, object] = {}
        export_services = {"fleet": object(), "scores": object()}

        def fake_iter_scores_table_inference_events(*_args, **kwargs):
            forwarded.update(kwargs)
            yield {"type": "globalPause", "paused": False}

        # Patch the owning module: scores.__init__ lazy-imports the events
        # helper (no package re-export) to keep the military import cycle broken.
        monkeypatch.setattr(
            inference_stream_rows,
            "iter_scores_table_inference_events",
            fake_iter_scores_table_inference_events,
        )

        stream = scores.iter_scores_table_inference_stream(
            sample_turn,
            (8,),
            game_id=628580,
            perspective=1,
            export_services=export_services,
        )

        assert next(stream) == {"type": "globalPause", "paused": False}
        assert forwarded["export_services"] is export_services
        assert forwarded.get("query_context") is None

    def test_iter_fleet_table_stream_keeps_factory_ctx_ensure_turn(
        self,
        analytics_service,
        monkeypatch,
    ):
        from api.analytics.fleet import fleet_table_stream_rows

        captured: dict[str, object] = {}

        def fake_iter(*_args, **kwargs):
            captured.update(kwargs)
            yield from ()

        monkeypatch.setattr(
            fleet_table_stream_rows,
            "iter_fleet_table_stream_events",
            fake_iter,
        )
        list(analytics_service.iter_fleet_table_stream(628580, 1, 111, (1,), username="captain"))
        query_ctx = captured["query_context"]
        assert query_ctx is not None
        assert query_ctx.ensure_turn is not None
        assert not hasattr(captured["fleet_services"], "ensure_turn")

        list(analytics_service.iter_fleet_table_stream(628580, 1, 111, (1,), username=""))
        assert captured["query_context"].ensure_turn is None

    def test_iter_scores_table_inference_stream_keeps_factory_ctx_ensure_turn(
        self,
        analytics_service,
        monkeypatch,
    ):
        from api.analytics.military_score_inference import inference_stream_rows

        captured: dict[str, object] = {}

        def fake_iter(*_args, **kwargs):
            captured.update(kwargs)
            yield {"type": "globalPause", "paused": False}

        monkeypatch.setattr(
            inference_stream_rows,
            "iter_scores_table_inference_events",
            fake_iter,
        )
        stream = analytics_service.iter_scores_table_inference_stream(
            628580, 1, 111, (8,), username="captain"
        )
        assert next(stream) == {"type": "globalPause", "paused": False}
        query_ctx = captured["query_context"]
        assert query_ctx is not None
        assert query_ctx.ensure_turn is not None

        list(
            analytics_service.iter_scores_table_inference_stream(628580, 1, 111, (8,), username="")
        )
        assert captured["query_context"].ensure_turn is None

    def test_factory_ctx_fills_a_fleet_chain_hole_when_username_is_set(self, sample_turn):
        """Login-backed ctx.ensure_turn auto-fetches a missing prior turn on DAG prepare."""
        from api.analytics.export_turn_fill import prepare_dependency_chain_turns
        from api.analytics.export_types import ExportScope
        from api.analytics.turn_roster import iter_turn_players
        from api.services.turn_analytic_service import TurnAnalyticService
        from api.storage.memory_asset import MemoryAssetBackend

        from tests.fixtures.export_framework.harness import clone_turn_at

        turns = {
            1: clone_turn_at(sample_turn, 1),
            3: clone_turn_at(sample_turn, 3),
        }
        fetched: list[int] = []

        class _Turns:
            def get_turn_info(self, game_id, perspective, turn_number):
                del game_id, perspective
                found = turns.get(turn_number)
                if found is None:
                    raise NotFoundError(f"turn {turn_number} is not stored")
                return found

            def list_stored_turn_numbers(self, game_id, perspective):
                del game_id, perspective
                return sorted(turns)

            def ensure_turn_loaded(self, game_id, perspective, turn_number, params, planets):
                del game_id, perspective, params, planets
                fetched.append(turn_number)
                turns[turn_number] = clone_turn_at(sample_turn, turn_number)
                return turns[turn_number]

        class _FakePlanets:
            @staticmethod
            def from_config():
                return object()

        svc = TurnAnalyticService(
            _Turns(),  # type: ignore[arg-type]
            storage=MemoryAssetBackend(initial={}),
            planets_client_factory=_FakePlanets.from_config,
        )
        _turn, ctx = svc._build_analytic_query_context(628580, 1, 3, username="captain")
        player_id = next(iter_turn_players(sample_turn)).id
        prepare_dependency_chain_turns(
            ctx,
            "fleet",
            ExportScope(
                game_id=628580,
                perspective=1,
                turn=3,
                player_id=player_id,
            ),
        )
        assert fetched == [2]

    def test_export_query_context_wires_hatch_read_without_table_compute(self, analytics_service):
        ctx = analytics_service.export_query_context(628580, 1, 111)
        result = ctx.hatch_read("connections", ["$"])
        assert result.status == "unavailable"
        assert result.reason == "empty_catalog"
        assert "scores" in ctx.export_services
        assert "fleet" in ctx.export_services
