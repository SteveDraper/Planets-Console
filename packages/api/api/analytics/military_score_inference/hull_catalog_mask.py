"""Race master hull catalogs and per-player hull catalog masks for build inference."""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.military_score_inference.inference_turn_lookup import (
    parse_component_id_csv,
    player_by_id,
    race_by_id_or_none,
)
from api.models.components import Hull
from api.models.game import GameSettings, TurnInfo

BIRD_ENLIGHTEN_HULL_ID = 106

REPLACEMENT_SETTING_FIELDS: tuple[str, ...] = (
    "repairshipreplacessagefrigate",
    "migtransportreplacesmigscout",
    "saurianlightfrigatereplacessaurian",
    "scorpiuscarrierreplacesscorpiuslight",
    "sscruiseriireplacessscruiser",
    "sscarrierplusreplacessscarrier",
    "skyfireplusreplacesskyfire",
    "d7creplacesd7a",
    "quietusplusreplacesquietus",
    "cybernautlightreplacescybernaut",
    "ironslavescoutreplacesironslave",
)


@dataclass(frozen=True)
class ResolvedHullCatalogMask:
    """Effective hull eligibility for one inference target player."""

    race_id: int
    race_name: str
    master_hull_ids: frozenset[int]
    default_enabled_hull_ids: frozenset[int]
    effective_enabled_hull_ids: frozenset[int]
    has_user_override: bool


def catalog_hull_ids(turn: TurnInfo) -> frozenset[int]:
    return frozenset(hull.id for hull in turn.hulls)


def hull_names_by_id(turn: TurnInfo) -> dict[int, str]:
    return {hull.id: hull.name for hull in turn.hulls}


def master_hull_ids_for_race(turn: TurnInfo, race_id: int) -> frozenset[int]:
    """All hull ids that may be buildable for a race on this turn snapshot."""
    race = race_by_id_or_none(turn, race_id)
    catalog_ids = catalog_hull_ids(turn)
    if race is None:
        return frozenset()
    race_hull_ids = parse_component_id_csv(race.hulls) | parse_component_id_csv(race.basehulls)
    return frozenset(race_hull_ids & catalog_ids)


def _apply_parent_child_swap(
    result: set[int],
    *,
    parent_id: int,
    child_id: int,
    race_hull_ids: frozenset[int],
) -> None:
    if child_id not in race_hull_ids or parent_id not in result:
        return
    result.discard(parent_id)
    result.add(child_id)


def swaps_for_enabled_settings(
    *,
    settings: GameSettings,
    hulls_by_id: dict[int, Hull],
    race_hull_ids: frozenset[int],
    base_hull_ids: frozenset[int],
) -> list[tuple[int, int]]:
    swaps: list[tuple[int, int]] = []
    if settings.repairshipreplacessagefrigate and 90 in base_hull_ids:
        swaps.append((90, 1090))
    for field in REPLACEMENT_SETTING_FIELDS:
        if field == "repairshipreplacessagefrigate":
            continue
        if not getattr(settings, field, False):
            continue
        for child_id in sorted(race_hull_ids):
            child = hulls_by_id.get(child_id)
            if child is None or child.parentid == 0:
                continue
            if child.parentid in base_hull_ids:
                swaps.append((child.parentid, child_id))
    return swaps


def standard_settings_adjusted_basehulls(
    *,
    race_id: int,
    race_basehulls_csv: str,
    race_hulls_csv: str,
    catalog_ids: frozenset[int],
    hulls_by_id: dict[int, Hull],
    settings: GameSettings,
) -> frozenset[int]:
    result = set(parse_component_id_csv(race_basehulls_csv) & catalog_ids)
    race_hull_ids = frozenset(parse_component_id_csv(race_hulls_csv) & catalog_ids)
    base_hull_ids = frozenset(result)

    for parent_id, child_id in swaps_for_enabled_settings(
        settings=settings,
        hulls_by_id=hulls_by_id,
        race_hull_ids=race_hull_ids,
        base_hull_ids=base_hull_ids,
    ):
        _apply_parent_child_swap(
            result,
            parent_id=parent_id,
            child_id=child_id,
            race_hull_ids=race_hull_ids,
        )

    if settings.birdshaveenlighten and race_id == 3 and BIRD_ENLIGHTEN_HULL_ID in race_hull_ids:
        result.add(BIRD_ENLIGHTEN_HULL_ID)

    return frozenset(result)


def default_enabled_hull_ids_for_player(turn: TurnInfo, player_id: int) -> frozenset[int]:
    """Initial hull mask before any user override, based on game type and loaded perspective."""
    catalog_ids = catalog_hull_ids(turn)
    if player_id == turn.player.id and turn.racehulls:
        return frozenset(turn.racehulls) & catalog_ids

    player = player_by_id(turn, player_id)
    race = race_by_id_or_none(turn, player.raceid)
    if race is None:
        return catalog_ids

    master = master_hull_ids_for_race(turn, player.raceid)
    if turn.settings.campaignmode:
        return frozenset(parse_component_id_csv(race.hulls) & catalog_ids) & master

    hulls_by_id = {hull.id: hull for hull in turn.hulls}
    enabled = standard_settings_adjusted_basehulls(
        race_id=player.raceid,
        race_basehulls_csv=race.basehulls,
        race_hulls_csv=race.hulls,
        catalog_ids=catalog_ids,
        hulls_by_id=hulls_by_id,
        settings=turn.settings,
    )
    return enabled & master


def resolve_hull_catalog_mask(
    turn: TurnInfo,
    player_id: int,
    *,
    user_enabled_hull_ids: frozenset[int] | None,
) -> ResolvedHullCatalogMask:
    player = player_by_id(turn, player_id)
    race = race_by_id_or_none(turn, player.raceid)
    race_name = race.name if race is not None else "Unknown"
    master = master_hull_ids_for_race(turn, player.raceid)
    default_enabled = default_enabled_hull_ids_for_player(turn, player_id)
    if user_enabled_hull_ids is None:
        effective = default_enabled
        has_override = False
    else:
        effective = user_enabled_hull_ids & master
        has_override = True
    return ResolvedHullCatalogMask(
        race_id=player.raceid,
        race_name=race_name,
        master_hull_ids=master,
        default_enabled_hull_ids=default_enabled,
        effective_enabled_hull_ids=effective,
        has_user_override=has_override,
    )
