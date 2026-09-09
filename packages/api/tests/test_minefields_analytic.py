"""Tests for the Minefields map analytic."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from api.analytics.minefields import ANALYTIC_ID, get_minefields_map
from api.models.space import Minefield, Nebula
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


def _sample_turn():
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        return turn_info_from_json(json.load(handle))


def _field(
    *,
    field_id: int,
    owner_id: int,
    units: int,
    x: int,
    y: int,
    is_web: bool = False,
    is_hidden: bool = False,
    info_turn: int = 111,
    friendly_code: str = "",
    radius: int = 0,
) -> Minefield:
    return Minefield(
        id=field_id,
        ownerid=owner_id,
        isweb=is_web,
        ishidden=is_hidden,
        units=units,
        infoturn=info_turn,
        friendlycode=friendly_code,
        x=x,
        y=y,
        radius=radius,
    )


def test_sample_minefields_round_trip_facts() -> None:
    turn = _sample_turn()
    data = get_minefields_map(turn)
    assert data["analyticId"] == ANALYTIC_ID
    assert data["nodes"] == []
    assert data["edges"] == []
    by_id = {row["id"]: row for row in data["minefields"]}
    assert set(by_id) == {18, 51, 52}

    first = by_id[18]
    assert first["ownerId"] == 2
    assert first["isWeb"] is False
    assert first["isHidden"] is False
    assert first["x"] == 2131
    assert first["y"] == 1417
    assert first["units"] == 85
    assert first["infoTurn"] == 111
    assert first["friendlyCode"] == "???"
    assert first["preRadius"] == 9
    assert first["postRadius"] == 8
    assert by_id[51]["preRadius"] == 48
    assert by_id[51]["postRadius"] == 46
    assert by_id[52]["preRadius"] == 18
    assert by_id[52]["postRadius"] == 17


def test_skips_non_positive_units() -> None:
    turn = _sample_turn()
    turn = replace(
        turn,
        minefields=[
            _field(field_id=1, owner_id=1, units=100, x=0, y=0),
            _field(field_id=2, owner_id=1, units=0, x=10, y=0),
            _field(field_id=3, owner_id=1, units=-4, x=20, y=0),
        ],
    )
    data = get_minefields_map(turn)
    assert [row["id"] for row in data["minefields"]] == [1]


def test_includes_hidden_fields_without_extra_style_flag() -> None:
    turn = _sample_turn()
    turn = replace(
        turn,
        minefields=[_field(field_id=9, owner_id=8, units=100, x=5, y=5, is_hidden=True)],
    )
    row = get_minefields_map(turn)["minefields"][0]
    assert row["isHidden"] is True
    assert "hiddenStyle" not in row


def test_prefers_units_over_stored_radius() -> None:
    turn = _sample_turn()
    turn = replace(
        turn,
        minefields=[_field(field_id=1, owner_id=1, units=100, x=0, y=0, radius=99)],
    )
    row = get_minefields_map(turn)["minefields"][0]
    assert row["preRadius"] == 10
    assert row["preRadius"] != 99


def test_nebula_overlap_uses_pre_decay_disk() -> None:
    turn = _sample_turn()
    field = _field(field_id=1, owner_id=1, units=100, x=0, y=0)
    nebula = Nebula(id=1, x=15, y=0, name="n", radius=5, intensity=10, gas=0)
    turn = replace(turn, minefields=[field], nebulas=[nebula])
    row = get_minefields_map(turn)["minefields"][0]
    # preRadius 10 + nebula 5 = 15, distance 15 => overlap, keep 0.85
    assert row["preRadius"] == 10
    assert row["postRadius"] == 9


def test_nominefields_still_computable() -> None:
    turn = _sample_turn()
    turn = replace(turn, settings=replace(turn.settings, nominefields=True))
    data = get_minefields_map(turn)
    assert data["analyticId"] == ANALYTIC_ID
    assert len(data["minefields"]) == 3
