"""Compare buildable-hull heuristics against per-perspective ground truth."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from api.analytics.military_score_inference.component_eligibility import (
    buildable_hull_ids_for_player,
)
from api.analytics.military_score_inference.hull_catalog_mask import (
    BIRD_ENLIGHTEN_HULL_ID,
    standard_settings_adjusted_basehulls,
)
from api.analytics.military_score_inference.inference_turn_lookup import (
    parse_component_id_csv,
    player_by_id,
    race_by_id_or_none,
)
from api.models.game import GameInfo, GameSettings, TurnInfo
from api.serialization.game import game_info_from_json
from api.serialization.turn import turn_info_from_json

HEURISTIC_LABELS: dict[str, str] = {
    "ground_truth": "Ground truth (player perspective turn.racehulls)",
    "current_code": "Current code (buildable_hull_ids_for_player)",
    "loaded_racehulls": "Loaded perspective turn.racehulls",
    "race_basehulls": "race.basehulls ∩ catalog",
    "race_hulls": "race.hulls ∩ catalog",
    "race_union": "(race.basehulls | race.hulls) ∩ catalog",
    "activehulls": "player.activehulls ∩ catalog",
    "fleet_hulls": "Fleet hull ids ∩ catalog",
    "standard_settings_adjusted": "Standard: basehulls + settings adjustments",
    "proposed_cross_player": "Proposed: perspective-aware synthesis",
    "catalog_all": "Full turn.hulls catalog",
}


@dataclass(frozen=True)
class HullSetComparison:
    heuristic_id: str
    hull_ids: frozenset[int]
    covers_ground_truth: bool
    missing_from_heuristic: frozenset[int]
    extra_in_heuristic: frozenset[int]
    overage: int


@dataclass(frozen=True)
class PlayerHullAnalysis:
    player_id: int
    username: str
    race_id: int
    race_name: str
    perspective_slot: int | None
    ground_truth: frozenset[int]
    fleet_hull_ids: frozenset[int]
    comparisons: tuple[HullSetComparison, ...]


@dataclass(frozen=True)
class HeuristicSummary:
    heuristic_id: str
    players_with_ground_truth: int
    players_covered: int
    avg_overage: float
    min_overage: int
    max_overage: int
    failed_player_ids: tuple[int, ...]


@dataclass(frozen=True)
class GameHullAnalysis:
    game_id: int
    game_name: str
    campaign_mode: bool
    host_turn: int
    loaded_perspective: int
    loaded_player_id: int
    loaded_race_name: str
    players: tuple[PlayerHullAnalysis, ...]
    heuristic_summaries: tuple[HeuristicSummary, ...]
    ground_truth_stable_across_turns: bool | None = None
    stability_note: str | None = None


def format_hull_id(hull_id: int, hull_names_by_id: dict[int, str]) -> str:
    name = hull_names_by_id.get(hull_id)
    if name:
        return f"{hull_id} ({name})"
    return str(hull_id)


def format_hull_set(
    hull_ids: frozenset[int] | set[int],
    hull_names_by_id: dict[int, str],
) -> str:
    if not hull_ids:
        return "(none)"
    return ", ".join(format_hull_id(hull_id, hull_names_by_id) for hull_id in sorted(hull_ids))


def hull_names_from_turn(turn: TurnInfo) -> dict[int, str]:
    return {hull.id: hull.name for hull in turn.hulls}


def catalog_hull_ids(turn: TurnInfo) -> frozenset[int]:
    return frozenset(hull.id for hull in turn.hulls)


def fleet_hull_ids_for_player(turn: TurnInfo, player_id: int) -> frozenset[int]:
    catalog = catalog_hull_ids(turn)
    return frozenset(
        ship.hullid
        for ship in (turn.ships or [])
        if ship.ownerid == player_id and ship.hullid in catalog
    )


def proposed_cross_player_hull_ids(
    turn: TurnInfo,
    player_id: int,
    *,
    settings: GameSettings,
) -> frozenset[int]:
    catalog_ids = catalog_hull_ids(turn)
    if player_id == turn.player.id and turn.racehulls:
        return frozenset(turn.racehulls) & catalog_ids

    player = player_by_id(turn, player_id)
    race = race_by_id_or_none(turn, player.raceid)
    if race is None:
        return catalog_ids

    if settings.campaignmode:
        return frozenset(parse_component_id_csv(race.hulls) & catalog_ids)

    hulls_by_id = {hull.id: hull for hull in turn.hulls}
    return standard_settings_adjusted_basehulls(
        race_id=player.raceid,
        race_basehulls_csv=race.basehulls,
        race_hulls_csv=race.hulls,
        catalog_ids=catalog_ids,
        hulls_by_id=hulls_by_id,
        settings=settings,
    )


def classify_gt_gap(
    hull_id: int,
    *,
    race_basehulls: frozenset[int],
    race_hulls: frozenset[int],
    hulls_by_id: dict[int, Hull],
) -> str:
    if hull_id in race_hulls and hull_id not in race_basehulls:
        hull = hulls_by_id.get(hull_id)
        if hull is not None and hull.parentid != 0:
            parent = hulls_by_id.get(hull.parentid)
            parent_label = f"{hull.parentid} ({parent.name})" if parent else str(hull.parentid)
            return f"campaign_or_replacement_variant (parent {parent_label})"
        if hull_id == BIRD_ENLIGHTEN_HULL_ID:
            return "birdshaveenlighten hull"
        return "in race.hulls only (not basehulls)"
    if hull_id not in race_hulls:
        return "not in race roster"
    return "in race.basehulls"


def compare_hull_set(
    *,
    heuristic_id: str,
    candidate: frozenset[int],
    ground_truth: frozenset[int],
) -> HullSetComparison:
    missing = ground_truth - candidate
    extra = candidate - ground_truth
    return HullSetComparison(
        heuristic_id=heuristic_id,
        hull_ids=candidate,
        covers_ground_truth=not missing,
        missing_from_heuristic=missing,
        extra_in_heuristic=extra,
        overage=len(extra),
    )


def build_heuristic_sets(
    turn: TurnInfo,
    player_id: int,
    *,
    settings: GameSettings,
) -> dict[str, frozenset[int]]:
    catalog_ids = catalog_hull_ids(turn)
    player = player_by_id(turn, player_id)
    race = race_by_id_or_none(turn, player.raceid)
    race_base = frozenset()
    race_hulls_set = frozenset()
    race_union = frozenset()
    if race is not None:
        race_base = frozenset(parse_component_id_csv(race.basehulls) & catalog_ids)
        race_hulls_set = frozenset(parse_component_id_csv(race.hulls) & catalog_ids)
        race_union = frozenset(
            parse_component_id_csv(race.basehulls) | parse_component_id_csv(race.hulls)
        )
        race_union &= catalog_ids

    hulls_by_id = {hull.id: hull for hull in turn.hulls}
    standard_adjusted = frozenset()
    if race is not None:
        standard_adjusted = standard_settings_adjusted_basehulls(
            race_id=player.raceid,
            race_basehulls_csv=race.basehulls,
            race_hulls_csv=race.hulls,
            catalog_ids=catalog_ids,
            hulls_by_id=hulls_by_id,
            settings=settings,
        )

    return {
        "current_code": buildable_hull_ids_for_player(turn, player_id),
        "loaded_racehulls": frozenset(turn.racehulls) & catalog_ids,
        "race_basehulls": race_base,
        "race_hulls": race_hulls_set,
        "race_union": race_union,
        "activehulls": frozenset(parse_component_id_csv(player.activehulls) & catalog_ids),
        "fleet_hulls": fleet_hull_ids_for_player(turn, player_id),
        "standard_settings_adjusted": standard_adjusted,
        "proposed_cross_player": proposed_cross_player_hull_ids(turn, player_id, settings=settings),
        "catalog_all": catalog_ids,
    }


def perspective_slots_for_game(storage_root: Path, game_id: int) -> list[int]:
    game_dir = storage_root / "games" / str(game_id)
    if not game_dir.is_dir():
        return []
    return sorted(
        int(path.name) for path in game_dir.iterdir() if path.is_dir() and path.name.isdigit()
    )


def load_turn_file(
    storage_root: Path,
    game_id: int,
    perspective: int,
    turn_number: int,
    *,
    settings_defaults: dict[str, Any],
) -> TurnInfo | None:
    turn_path = (
        storage_root / "games" / str(game_id) / str(perspective) / "turns" / f"{turn_number}.json"
    )
    if not turn_path.is_file():
        return None
    with turn_path.open() as handle:
        return turn_info_from_json(json.load(handle), settings_defaults=settings_defaults)


def ground_truth_by_player(
    storage_root: Path,
    game_id: int,
    turn_number: int,
    *,
    settings_defaults: dict[str, Any],
    perspective_slots: list[int],
) -> dict[int, tuple[frozenset[int], int]]:
    """Map player id -> (ground_truth hull ids, perspective slot)."""
    ground_truth: dict[int, tuple[frozenset[int], int]] = {}
    for perspective in perspective_slots:
        turn = load_turn_file(
            storage_root,
            game_id,
            perspective,
            turn_number,
            settings_defaults=settings_defaults,
        )
        if turn is None:
            continue
        catalog = catalog_hull_ids(turn)
        player_id = turn.player.id
        gt = frozenset(turn.racehulls) & catalog
        ground_truth[player_id] = (gt, perspective)
    return ground_truth


def check_ground_truth_stability(
    storage_root: Path,
    game_id: int,
    *,
    settings_defaults: dict[str, Any],
    perspective_slots: list[int],
    reference_turn: int,
    compare_turn: int,
) -> tuple[bool, str]:
    mismatches: list[str] = []
    for perspective in perspective_slots:
        ref = load_turn_file(
            storage_root,
            game_id,
            perspective,
            reference_turn,
            settings_defaults=settings_defaults,
        )
        other = load_turn_file(
            storage_root,
            game_id,
            perspective,
            compare_turn,
            settings_defaults=settings_defaults,
        )
        if ref is None or other is None:
            continue
        ref_gt = frozenset(ref.racehulls)
        other_gt = frozenset(other.racehulls)
        if ref_gt != other_gt:
            mismatches.append(
                f"perspective {perspective} player {ref.player.id}: "
                f"turn {reference_turn} vs {compare_turn}"
            )
    if not mismatches:
        return True, f"Identical ground truth on turns {reference_turn} and {compare_turn}"
    return False, "; ".join(mismatches[:5])


def analyze_game(
    storage_root: Path,
    game_id: int,
    *,
    host_turn: int,
    loaded_perspective: int,
    settings_defaults: dict[str, Any],
    game_info: GameInfo,
    compare_turn: int | None = None,
) -> GameHullAnalysis:
    loaded_turn = load_turn_file(
        storage_root,
        game_id,
        loaded_perspective,
        host_turn,
        settings_defaults=settings_defaults,
    )
    if loaded_turn is None:
        raise FileNotFoundError(
            "missing turn file for game "
            f"{game_id} perspective {loaded_perspective} turn {host_turn}"
        )

    perspective_slots = perspective_slots_for_game(storage_root, game_id)
    gt_by_player = ground_truth_by_player(
        storage_root,
        game_id,
        host_turn,
        settings_defaults=settings_defaults,
        perspective_slots=perspective_slots,
    )
    settings = loaded_turn.settings

    player_analyses: list[PlayerHullAnalysis] = []
    for player_id, (ground_truth, perspective_slot) in sorted(gt_by_player.items()):
        if not ground_truth:
            continue
        player = player_by_id(loaded_turn, player_id)
        race = race_by_id_or_none(loaded_turn, player.raceid)
        heuristics = build_heuristic_sets(loaded_turn, player_id, settings=settings)
        comparisons = tuple(
            compare_hull_set(
                heuristic_id=heuristic_id,
                candidate=candidate,
                ground_truth=ground_truth,
            )
            for heuristic_id, candidate in heuristics.items()
        )
        player_analyses.append(
            PlayerHullAnalysis(
                player_id=player_id,
                username=player.username,
                race_id=player.raceid,
                race_name=race.name if race is not None else "Unknown",
                perspective_slot=perspective_slot,
                ground_truth=ground_truth,
                fleet_hull_ids=fleet_hull_ids_for_player(loaded_turn, player_id),
                comparisons=comparisons,
            )
        )

    heuristic_summaries = summarize_heuristics(player_analyses)

    stable: bool | None = None
    stability_note: str | None = None
    if compare_turn is not None and compare_turn != host_turn:
        stable, stability_note = check_ground_truth_stability(
            storage_root,
            game_id,
            settings_defaults=settings_defaults,
            perspective_slots=perspective_slots,
            reference_turn=host_turn,
            compare_turn=compare_turn,
        )

    loaded_race = race_by_id_or_none(loaded_turn, loaded_turn.player.raceid)
    return GameHullAnalysis(
        game_id=game_id,
        game_name=game_info.game.name,
        campaign_mode=settings.campaignmode,
        host_turn=host_turn,
        loaded_perspective=loaded_perspective,
        loaded_player_id=loaded_turn.player.id,
        loaded_race_name=loaded_race.name if loaded_race is not None else "Unknown",
        players=tuple(player_analyses),
        heuristic_summaries=heuristic_summaries,
        ground_truth_stable_across_turns=stable,
        stability_note=stability_note,
    )


def summarize_heuristics(players: list[PlayerHullAnalysis]) -> tuple[HeuristicSummary, ...]:
    heuristic_order = (
        "current_code",
        "loaded_racehulls",
        "race_basehulls",
        "race_hulls",
        "standard_settings_adjusted",
        "proposed_cross_player",
        "activehulls",
        "fleet_hulls",
        "catalog_all",
    )
    summaries: list[HeuristicSummary] = []
    for heuristic_id in heuristic_order:
        comparisons_by_player: list[tuple[int, HullSetComparison]] = []
        for player in players:
            comparison = next(
                (entry for entry in player.comparisons if entry.heuristic_id == heuristic_id),
                None,
            )
            if comparison is not None:
                comparisons_by_player.append((player.player_id, comparison))
        if not comparisons_by_player:
            continue
        covered = [
            comparison for _, comparison in comparisons_by_player if comparison.covers_ground_truth
        ]
        overages = [comparison.overage for comparison in covered]
        summaries.append(
            HeuristicSummary(
                heuristic_id=heuristic_id,
                players_with_ground_truth=len(comparisons_by_player),
                players_covered=len(covered),
                avg_overage=sum(overages) / len(overages) if overages else 0.0,
                min_overage=min(overages) if overages else 0,
                max_overage=max(overages) if overages else 0,
                failed_player_ids=tuple(
                    player_id
                    for player_id, comparison in comparisons_by_player
                    if not comparison.covers_ground_truth
                ),
            )
        )
    return tuple(summaries)


def analysis_to_json(analysis: GameHullAnalysis, hull_names: dict[int, str]) -> dict[str, Any]:
    return {
        "gameId": analysis.game_id,
        "gameName": analysis.game_name,
        "campaignMode": analysis.campaign_mode,
        "hostTurn": analysis.host_turn,
        "loadedPerspective": analysis.loaded_perspective,
        "loadedPlayerId": analysis.loaded_player_id,
        "loadedRaceName": analysis.loaded_race_name,
        "groundTruthStableAcrossTurns": analysis.ground_truth_stable_across_turns,
        "stabilityNote": analysis.stability_note,
        "heuristicSummaries": [
            {
                "heuristicId": summary.heuristic_id,
                "label": HEURISTIC_LABELS.get(summary.heuristic_id, summary.heuristic_id),
                "playersWithGroundTruth": summary.players_with_ground_truth,
                "playersCovered": summary.players_covered,
                "avgOverage": round(summary.avg_overage, 2),
                "minOverage": summary.min_overage,
                "maxOverage": summary.max_overage,
                "failedPlayerIds": list(summary.failed_player_ids),
            }
            for summary in analysis.heuristic_summaries
        ],
        "players": [
            {
                "playerId": player.player_id,
                "username": player.username,
                "raceId": player.race_id,
                "raceName": player.race_name,
                "perspectiveSlot": player.perspective_slot,
                "groundTruth": [
                    format_hull_id(hull_id, hull_names) for hull_id in sorted(player.ground_truth)
                ],
                "fleetHulls": [
                    format_hull_id(hull_id, hull_names) for hull_id in sorted(player.fleet_hull_ids)
                ],
                "heuristics": [
                    {
                        "heuristicId": comparison.heuristic_id,
                        "label": HEURISTIC_LABELS.get(
                            comparison.heuristic_id,
                            comparison.heuristic_id,
                        ),
                        "coversGroundTruth": comparison.covers_ground_truth,
                        "overage": comparison.overage,
                        "missing": [
                            format_hull_id(hull_id, hull_names)
                            for hull_id in sorted(comparison.missing_from_heuristic)
                        ],
                        "extra": [
                            format_hull_id(hull_id, hull_names)
                            for hull_id in sorted(comparison.extra_in_heuristic)
                        ],
                    }
                    for comparison in player.comparisons
                ],
            }
            for player in analysis.players
        ],
    }


def format_text_report(
    analysis: GameHullAnalysis,
    hull_names: dict[int, str],
    *,
    hulls_by_id: dict[int, Hull],
) -> list[str]:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(
        f"Game {analysis.game_id} ({analysis.game_name}) "
        f"turn {analysis.host_turn} -- loaded perspective {analysis.loaded_perspective}"
    )
    lines.append(
        f"Campaign: {analysis.campaign_mode} | "
        f"Loaded player: {analysis.loaded_player_id} ({analysis.loaded_race_name})"
    )
    if analysis.stability_note:
        stable_label = "yes" if analysis.ground_truth_stable_across_turns else "no"
        lines.append(
            f"Ground truth stable across turns: {stable_label} -- {analysis.stability_note}"
        )
    lines.append("")
    lines.append("Heuristic summary (smallest avg overage with full coverage is best):")
    for summary in analysis.heuristic_summaries:
        label = HEURISTIC_LABELS.get(summary.heuristic_id, summary.heuristic_id)
        lines.append(
            f"  {summary.heuristic_id}: "
            f"{summary.players_covered}/{summary.players_with_ground_truth} covered, "
            f"avg overage {summary.avg_overage:.1f}, "
            f"max overage {summary.max_overage}"
        )
        if summary.failed_player_ids:
            lines.append(f"    failed players: {list(summary.failed_player_ids)}")
        lines.append(f"    {label}")

    lines.append("")
    lines.append("Per-player detail:")

    for player in analysis.players:
        lines.append("")
        lines.append(
            f"Player {player.player_id} ({player.username}) -- "
            f"{player.race_name} (race {player.race_id}), "
            f"ground truth from perspective {player.perspective_slot}"
        )
        lines.append(
            f"  Ground truth ({len(player.ground_truth)}): "
            f"{format_hull_set(player.ground_truth, hull_names)}"
        )
        if player.fleet_hull_ids:
            lines.append(
                f"  Fleet hulls ({len(player.fleet_hull_ids)}): "
                f"{format_hull_set(player.fleet_hull_ids, hull_names)}"
            )
        else:
            lines.append("  Fleet hulls: (none in catalog)")

        for comparison in player.comparisons:
            if comparison.heuristic_id in {"ground_truth", "race_union"}:
                continue
            status = "OK" if comparison.covers_ground_truth else "FAIL"
            label = HEURISTIC_LABELS.get(comparison.heuristic_id, comparison.heuristic_id)
            lines.append(
                f"  [{status}] {comparison.heuristic_id} "
                f"(size {len(comparison.hull_ids)}, overage {comparison.overage}): {label}"
            )
            if comparison.missing_from_heuristic:
                lines.append(
                    f"      missing ({len(comparison.missing_from_heuristic)}): "
                    f"{format_hull_set(comparison.missing_from_heuristic, hull_names)}"
                )
            if comparison.extra_in_heuristic and comparison.overage <= 12:
                lines.append(
                    f"      extra ({len(comparison.extra_in_heuristic)}): "
                    f"{format_hull_set(comparison.extra_in_heuristic, hull_names)}"
                )
            elif comparison.extra_in_heuristic:
                extra_count = len(comparison.extra_in_heuristic)
                lines.append(f"      extra: {extra_count} hulls (list omitted)")

        base_set = next(
            (
                comparison.hull_ids
                for comparison in player.comparisons
                if comparison.heuristic_id == "race_basehulls"
            ),
            frozenset(),
        )
        race_hulls_set = next(
            (
                comparison.hull_ids
                for comparison in player.comparisons
                if comparison.heuristic_id == "race_hulls"
            ),
            frozenset(),
        )
        gaps = player.ground_truth - base_set
        if gaps:
            lines.append(f"  GT gaps vs race.basehulls ({len(gaps)}):")
            for hull_id in sorted(gaps):
                classification = classify_gt_gap(
                    hull_id,
                    race_basehulls=base_set,
                    race_hulls=race_hulls_set,
                    hulls_by_id=hulls_by_id,
                )
                lines.append(f"      {format_hull_id(hull_id, hull_names)} -- {classification}")

    return lines


def discover_game_ids(storage_root: Path) -> list[int]:
    games_dir = storage_root / "games"
    if not games_dir.is_dir():
        return []
    return sorted(
        int(path.name)
        for path in games_dir.iterdir()
        if path.is_dir() and path.name.isdigit() and (path / "info.json").is_file()
    )


def load_game_info(storage_root: Path, game_id: int) -> tuple[GameInfo, dict[str, Any]]:
    info_path = storage_root / "games" / str(game_id) / "info.json"
    with info_path.open() as handle:
        raw = json.load(handle)
    return game_info_from_json(raw), raw["settings"]
