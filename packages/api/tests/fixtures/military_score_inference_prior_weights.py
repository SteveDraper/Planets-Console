"""Shared hull and catalog helpers for prior-weights catalog tests."""

from dataclasses import replace

from api.analytics.military_score_inference.hull_category import BATTLESHIP_MASS_THRESHOLD
from api.analytics.military_score_inference.prior_weights import (
    PriorWeightsCatalog,
    PriorWeightsDiagnostics,
    _prior_weights_catalog_from_tables,
)
from api.models.components import Hull


def beam_ship_hull() -> Hull:
    return Hull(
        id=24,
        name="Serpent Class Escort",
        tritanium=33,
        duranium=15,
        molybdenum=5,
        fueltank=160,
        crew=35,
        engines=1,
        mass=55,
        techlevel=1,
        cargo=20,
        fighterbays=0,
        launchers=0,
        beams=2,
        cancloak=False,
        cost=40,
        special="",
        description="",
        advantage=0,
        isbase=False,
        dur=0,
        tri=0,
        mol=0,
        mc=0,
        parentid=0,
        academy=False,
    )


def torpedo_hull() -> Hull:
    return Hull(
        id=65,
        name="Torpedo Frigate",
        tritanium=20,
        duranium=10,
        molybdenum=5,
        fueltank=120,
        crew=40,
        engines=1,
        mass=80,
        techlevel=2,
        cargo=20,
        fighterbays=0,
        launchers=2,
        beams=1,
        cancloak=False,
        cost=50,
        special="",
        description="",
        advantage=0,
        isbase=False,
        dur=0,
        tri=0,
        mol=0,
        mc=0,
        parentid=0,
        academy=False,
    )


def battleship_hull() -> Hull:
    return replace(
        torpedo_hull(),
        id=90,
        name="Heavy Battleship",
        mass=BATTLESHIP_MASS_THRESHOLD + 50,
        beams=4,
        launchers=4,
    )


def minimal_prior_catalog(
    *,
    hull_log_weights: dict[int, int] | None = None,
    combo_log_overrides: dict[str, int] | None = None,
    hull_log_overrides: dict[int, int] | None = None,
) -> PriorWeightsCatalog:
    return _prior_weights_catalog_from_tables(
        diagnostics=PriorWeightsDiagnostics(
            category_id="standard",
            asset_path="test",
            asset_version=1,
            game_category_rules_version=1,
            fell_back_to_standard=False,
            ship_limit_band="before_ship_limit",
            race_id_used=None,
        ),
        hull_log_weights=hull_log_weights or {},
        component_tables={},
        aggregate_action_weights={},
        aggregate_bucket_marginal_weights={},
        combo_log_overrides=combo_log_overrides or {},
        hull_log_overrides=hull_log_overrides or {},
    )
