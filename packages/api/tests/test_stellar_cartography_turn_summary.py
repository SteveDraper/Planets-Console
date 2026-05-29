"""Tests for lightweight Stellar Cartography turn summaries."""

import copy
import json
from pathlib import Path

import pytest
from api.concepts.stellar_cartography.turn_summary import stellar_cartography_turn_summary
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def stellar_cartography_turn():
    with open(ASSETS_DIR / "turn_stellar_cartography_sample.json") as f:
        return turn_info_from_json(json.load(f))


def test_turn_summary_reports_ion_storm_count(stellar_cartography_turn):
    summary = stellar_cartography_turn_summary(stellar_cartography_turn)
    assert summary == {
        "ion_storm_count": len(stellar_cartography_turn.ionstorms),
        "nu_ion_storms": True,
    }


def test_turn_summary_reports_empty_ion_storms(stellar_cartography_turn):
    turn = copy.deepcopy(stellar_cartography_turn)
    turn.ionstorms = []
    summary = stellar_cartography_turn_summary(turn)
    assert summary["ion_storm_count"] == 0


def test_turn_summary_reports_classic_ion_storm_mode(stellar_cartography_turn):
    turn = copy.deepcopy(stellar_cartography_turn)
    turn.settings.nuionstorms = False
    summary = stellar_cartography_turn_summary(turn)
    assert summary["nu_ion_storms"] is False
