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

# Fixed standard-settings replacements. Each flag maps to exactly one
# (parent_out, child_in) pair -- not every campaign child of a base hull.
# Several children are not direct parentid descendants of the stock hull.
STANDARD_HULL_REPLACEMENT_SWAPS: tuple[tuple[str, int, int], ...] = (
    ("repairshipreplacessagefrigate", 90, 1090),  # Sage Frigate -> Sage Repair
    ("migtransportreplacesmigscout", 73, 1073),  # Mig Scout -> Mig Transport
    ("saurianlightfrigatereplacessaurian", 25, 3025),  # Saurian LC -> Light Frigate
    ("scorpiuscarrierreplacesscorpiuslight", 102, 1102),  # Scorpius Light -> Carrier
    ("sscruiseriireplacessscruiser", 74, 1074),  # Super Star Cruiser -> II
    ("sscarrierplusreplacessscarrier", 76, 2076),  # Super Star Carrier -> Carrier+
    ("skyfireplusreplacesskyfire", 48, 2048),  # Skyfire -> Skyfire+
    ("d7creplacesd7a", 34, 2034),  # D7a Painmaker -> D7c
    ("quietusplusreplacesquietus", 58, 1058),  # Quietus -> Quietus+
    ("cybernautlightreplacescybernaut", 83, 2083),  # Cybernaut -> Light Baseship
    ("ironslavescoutreplacesironslave", 85, 2085),  # Iron Slave -> Scout
)

# Backward-compatible alias for callers that iterate setting field names only.
REPLACEMENT_SETTING_FIELDS: tuple[str, ...] = tuple(
    field for field, _parent_id, _child_id in STANDARD_HULL_REPLACEMENT_SWAPS
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
    base_hull_ids: frozenset[int],
    hulls_by_id: dict[int, Hull] | None = None,
    race_hull_ids: frozenset[int] | None = None,
) -> list[tuple[int, int]]:
    """Return enabled standard (parent, child) swaps for hulls in ``base_hull_ids``.

    ``hulls_by_id`` and ``race_hull_ids`` remain accepted for call-site compatibility;
    child presence in the race hull list is enforced by ``_apply_parent_child_swap``.
    """
    _ = hulls_by_id, race_hull_ids
    swaps: list[tuple[int, int]] = []
    for field, parent_id, child_id in STANDARD_HULL_REPLACEMENT_SWAPS:
        if not getattr(settings, field, False):
            continue
        if parent_id not in base_hull_ids:
            continue
        swaps.append((parent_id, child_id))
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
