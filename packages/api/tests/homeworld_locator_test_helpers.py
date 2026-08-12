"""Shared planet construction for homeworld locator unit tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from api.models.game import TurnInfo
from api.models.planet import Planet
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


def load_sample_turn() -> TurnInfo:
    raw = json.loads((ASSETS_DIR / "turn_sample.json").read_text(encoding="utf-8"))
    return turn_info_from_json(raw, settings_defaults=raw["settings"])


def load_sample_template_planet() -> Planet:
    return load_sample_turn().planets[0]


def _planet(
    template: Planet,
    *,
    planet_id: int,
    x: int,
    y: int,
    ownerid: int = 0,
    clans: int = 0,
    temp: int = 0,
    debrisdisk: int = 0,
) -> Planet:
    return replace(
        template,
        id=planet_id,
        name=f"P{planet_id}",
        x=x,
        y=y,
        ownerid=ownerid,
        clans=clans,
        temp=temp,
        debrisdisk=debrisdisk,
    )
