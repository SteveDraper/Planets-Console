"""Later-file refresh re-checks the target after the rebuild."""

from __future__ import annotations

from api.analytics.fleet.approximate_fleet import refresh_following_approximate_fleets
from api.analytics.fleet.chain import get_or_materialize_fleet_ledger_for_player
from api.analytics.fleet.serialization import persisted_fleet_ledger_to_json

from tests.test_approximate_fleet import (
    _bind,
    _known_ship_ids,
    _prior,
    _put,
    _record,
    _stored,
    _turn,
)


def test_later_refresh_skips_put_when_ensure_final_lands_during_rebuild(monkeypatch) -> None:
    import api.analytics.fleet.approximate_fleet as approximate_fleet

    turn4 = _turn(turn_number=4, ship_ids=(8,), capitalships=3, freighters=0)
    turn5 = _turn(turn_number=5, ship_ids=(21,), capitalships=3, freighters=0)
    turn6 = _turn(turn_number=6, ship_ids=(30,), capitalships=3, freighters=0)
    services, _ctx, player_id = _bind(turn5, turn4, turn6)
    _put(services, player_id, 4, _prior(player_id, [_record("kept-ship", ship_id=11)], final=True))
    _put(services, player_id, 6, _prior(player_id, [_record("stale-ship", ship_id=99)]))
    generation = services.persistence.player_invalidation_generation(
        services.game_id,
        services.perspective,
        player_id,
    )
    sealed: dict[str, object] = {}
    real_after_prior = approximate_fleet.fleet_ledger_after_prior

    def store_ensure_final_during_rebuild(*args, **kwargs):
        before_put = services.persistence.player_invalidation_generation(
            services.game_id,
            services.perspective,
            player_id,
        )
        _put(
            services,
            player_id,
            6,
            _prior(player_id, [_record("closed-ship", ship_id=77)], final=True),
        )
        after_put = services.persistence.player_invalidation_generation(
            services.game_id,
            services.perspective,
            player_id,
        )
        assert before_put == after_put == generation
        sealed["ledger"] = persisted_fleet_ledger_to_json(_stored(services, player_id, 6))
        return real_after_prior(*args, **kwargs)

    monkeypatch.setattr(
        approximate_fleet,
        "fleet_ledger_after_prior",
        store_ensure_final_during_rebuild,
    )

    saved = get_or_materialize_fleet_ledger_for_player(
        services.persistence,
        services.game_id,
        services.perspective,
        player_id,
        turn5,
        load_turn=services.load_turn,
    )

    stored = _stored(services, player_id, 6)
    assert 21 in _known_ship_ids(saved)
    assert sealed["ledger"] == persisted_fleet_ledger_to_json(stored)
    assert services.persistence.ledger_is_ensure_final(
        services.game_id,
        services.perspective,
        6,
        player_id,
        stored,
    )
    assert (
        services.persistence.player_invalidation_generation(
            services.game_id,
            services.perspective,
            player_id,
        )
        == generation
    )


def test_refresh_does_no_work_when_saved_turn_meets_the_stop() -> None:
    """A saved turn at or past the ceiling reads nothing and writes nothing."""

    class _CountingPersistence:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def player_invalidation_generation(self, *_args: object, **_kwargs: object) -> int:
            self.calls.append("generation")
            return 0

        def get_ledger(self, *_args: object, **_kwargs: object) -> None:
            self.calls.append("get_ledger")
            return None

        def ledger_is_ensure_final(self, *_args: object, **_kwargs: object) -> bool:
            self.calls.append("ensure_final")
            return False

        def put_ledger(self, *_args: object, **_kwargs: object) -> None:
            self.calls.append("put_ledger")
            return None

    def assert_no_work(saved_turn: int, stop_after_turn: int) -> None:
        persistence = _CountingPersistence()

        def load_turn(turn_number: int) -> None:
            persistence.calls.append(f"load:{turn_number}")
            return None

        refresh_following_approximate_fleets(
            persistence=persistence,  # type: ignore[arg-type]
            game_id=1,
            perspective=1,
            player_id=1,
            saved_turn=saved_turn,
            player_invalidation_generation=0,
            load_turn=load_turn,
            inference_materialization=None,
            stop_after_turn=stop_after_turn,
        )
        assert persistence.calls == []

    assert_no_work(5, 5)
    assert_no_work(6, 5)
