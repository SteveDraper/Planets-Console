#!/usr/bin/env python3
"""Enumerate early-stop score collisions that hide higher-tech hull builds.

Finds pure single-warship construction scores where:
1. At least one early-tier (hull tech band) member has ship-only plausibility at or
   above ``shipOnlyExactEarlyStopMinPlausibility`` (would trigger ladder early stop), and
2. At least one member uses a hull admitted only after hulls are fully widened.

The high-tech hull ids in those collisions are the candidate early-tier hull allowlist.

Also emits checked-in twin assets (``--write-asset``) consumed by inference for the
conditional collision-hull-widen tier (#226):

  uv run python scripts/early_stop_hull_collisions.py --game-type epic --write-asset

Outputs ``assets/analytics/scores/hull_collision_twins_{standard,epic,campaign}.yaml``.
Regenerate when prior weights or component catalogs change.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parents[1] / "packages" / "api"
_api_root_str = str(_API_ROOT)
if _api_root_str in sys.path:
    sys.path.remove(_api_root_str)
sys.path.insert(0, _api_root_str)

import typer  # noqa: E402
from api.analytics.military_score_inference.actions import (  # noqa: E402
    build_action_catalog,
)
from api.analytics.military_score_inference.component_eligibility import (  # noqa: E402
    turn_catalog_context_for_policy_step,
)
from api.analytics.military_score_inference.hull_catalog_mask import (  # noqa: E402
    resolve_hull_catalog_mask,
)
from api.analytics.military_score_inference.hull_collision_twins_asset import (  # noqa: E402
    HullCollisionTwinsAsset,
    HullCollisionTwinsProvenance,
    HullCollisionTwinTriple,
    build_twins_asset,
    default_twin_asset_path,
    default_twin_assets_dir,
    write_hull_collision_twins_asset,
)
from api.analytics.military_score_inference.models import (  # noqa: E402
    InferenceObservation,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.prior_weights_asset import (  # noqa: E402
    default_prior_weights_dir,
)
from api.analytics.military_score_inference.prior_weights_resolve import (  # noqa: E402
    resolve_prior_weights_catalog,
)
from api.analytics.military_score_inference.ranking_heuristics import (  # noqa: E402
    ranking_penalty_from_marginal_weight,
)
from api.analytics.military_score_inference.tier_policy import (  # noqa: E402
    InferenceTierPolicyStep,
    resolve_solver_thresholds,
    resolve_tier_policies,
)
from api.concepts.game_category import GameCategory  # noqa: E402
from api.models.game import GameSettings, TurnInfo  # noqa: E402
from api.models.player import Player  # noqa: E402
from api.serialization.game import game_info_from_json  # noqa: E402
from api.serialization.turn import turn_info_from_json  # noqa: E402

app = typer.Typer(
    add_completion=False,
    help=(
        "List single-ship military-score collisions that can cause incorrect "
        "early-stop before higher-tech hulls are admitted. "
        "Use --write-asset to emit hull_collision_twins_{category}.yaml."
    ),
)

GAME_TYPE_CHOICES = tuple(c.value for c in GameCategory if c != GameCategory.UNKNOWN)


@dataclass(frozen=True)
class ComboRef:
    combo_id: str
    label: str
    hull_id: int
    hull_name: str
    hull_techlevel: int
    engine_id: int
    beam_id: int | None
    torp_id: int | None
    beam_count: int
    launcher_count: int
    probability_weight: int
    ship_only_objective: int | None = None


@dataclass(frozen=True)
class ScoreCollision:
    race_id: int
    race_name: str
    military_change: int
    score_delta_2x: int
    early_trigger_members: tuple[ComboRef, ...]
    high_tech_members: tuple[ComboRef, ...]


@dataclass(frozen=True)
class RaceCollisionReport:
    race_id: int
    race_name: str
    early_combo_count: int
    widen_combo_count: int
    early_trigger_score_count: int
    collisions: tuple[ScoreCollision, ...]
    allowlist_hull_ids: tuple[int, ...]


@dataclass(frozen=True)
class CollisionCensus:
    game_type: str
    prior_asset_path: str
    prior_fell_back_to_standard: bool
    catalog_game_id: int
    catalog_host_turn: int
    catalog_perspective: int
    catalog_native_game_type: str
    early_stop_min_plausibility: int
    early_policy_step_id: str
    widen_hulls_policy_step_id: str
    races: tuple[RaceCollisionReport, ...]
    allowlist_hull_ids: tuple[int, ...]
    allowlist_hulls: tuple[tuple[int, str, int], ...]  # id, name, techlevel


def _default_storage_root() -> Path:
    return Path(".data")


def parse_game_type(raw: str) -> GameCategory:
    try:
        category = GameCategory(raw.lower())
    except ValueError as exc:
        allowed = ", ".join(GAME_TYPE_CHOICES)
        raise ValueError(f"unknown game type {raw!r}; expected one of: {allowed}") from exc
    if category == GameCategory.UNKNOWN:
        raise ValueError("game type 'unknown' is not supported")
    return category


def coerce_settings_for_category(settings: GameSettings, category: GameCategory) -> GameSettings:
    """Shape settings so ``GameCategory.from_game_settings`` matches ``category``."""
    if category == GameCategory.CAMPAIGN:
        return replace(settings, campaignmode=True)
    if category == GameCategory.BLITZ:
        return replace(settings, campaignmode=False, endturn=min(settings.endturn, 30))
    if category == GameCategory.EPIC:
        return replace(
            settings,
            campaignmode=False,
            endturn=max(settings.endturn, 31),
            shiplimit=max(settings.shiplimit, 500),
        )
    if category == GameCategory.STANDARD:
        shiplimit = settings.shiplimit
        if shiplimit >= 500:
            shiplimit = 499
        return replace(
            settings,
            campaignmode=False,
            endturn=max(settings.endturn, 31),
            shiplimit=shiplimit,
        )
    raise ValueError(f"unsupported game category: {category}")


def first_full_hulls_policy_step(
    policy_steps: tuple[InferenceTierPolicyStep, ...],
) -> InferenceTierPolicyStep:
    for step in policy_steps:
        if step.filters.hulls.all:
            return step
    raise ValueError("tier policy has no step with filters.hulls.all")


def ship_only_objective(probability_weight: int, *, max_combo_weight: int) -> int:
    return -ranking_penalty_from_marginal_weight(
        probability_weight,
        max_marginal_weight=max_combo_weight,
    )


def _combo_ref(
    combo: ShipBuildCombo,
    *,
    hull_name: str,
    hull_techlevel: int,
    ship_only_objective_value: int | None = None,
) -> ComboRef:
    return ComboRef(
        combo_id=combo.combo_id,
        label=combo.labels[0] if combo.labels else combo.combo_id,
        hull_id=combo.hull_id,
        hull_name=hull_name,
        hull_techlevel=hull_techlevel,
        engine_id=combo.engine_id,
        beam_id=combo.beam_id,
        torp_id=combo.torp_id,
        beam_count=combo.beam_count,
        launcher_count=combo.launcher_count,
        probability_weight=combo.probability_weight,
        ship_only_objective=ship_only_objective_value,
    )


def _single_warship_combos(combos: tuple[ShipBuildCombo, ...]) -> tuple[ShipBuildCombo, ...]:
    return tuple(
        combo
        for combo in combos
        if combo.warship_delta == 1 and combo.freighter_delta == 0 and combo.score_delta_2x != 0
    )


def _player_for_race(turn: TurnInfo, race_id: int) -> Player | None:
    return next((player for player in turn.players if player.raceid == race_id), None)


def _dummy_observation(player_id: int) -> InferenceObservation:
    return InferenceObservation(
        player_id=player_id,
        turn=1,
        military_delta_2x=2,
        warship_delta=1,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=1,
        is_after_ship_limit=False,
        military_partition_slack_2x=1,
        scoreboard_delta_source="reported_change_fields",
    )


def _build_catalog_for_step(
    turn: TurnInfo,
    player: Player,
    policy_step: InferenceTierPolicyStep,
    *,
    policy_step_index: int,
    prior_weights_base_dir: Path | None,
) -> tuple[tuple[ShipBuildCombo, ...], str]:
    observation = _dummy_observation(player.id)
    mask = resolve_hull_catalog_mask(turn, player.id, user_enabled_hull_ids=None)
    catalog_context = turn_catalog_context_for_policy_step(
        turn,
        player.id,
        policy_step,
        resolved_mask=mask,
    )
    prior_catalog = resolve_prior_weights_catalog(
        observation,
        turn.settings,
        race_id=player.raceid,
        buildable_hull_ids=catalog_context.buildable_hull_ids,
        generic_freighter_hull_ids=frozenset(
            hull_id
            for hull_id in catalog_context.buildable_hull_ids
            if (hull := catalog_context.hulls_by_id.get(hull_id)) is not None
            and hull.fighterbays == 0
            and hull.launchers == 0
            and hull.beams == 0
        ),
        eligible_engine_ids=catalog_context.eligible_engine_ids,
        eligible_beam_ids=catalog_context.eligible_beam_ids,
        eligible_torp_ids=catalog_context.eligible_torp_ids,
        base_dir=prior_weights_base_dir,
    )
    catalog = build_action_catalog(
        observation,
        hulls_by_id=catalog_context.hulls_by_id,
        engines_by_id=catalog_context.engines_by_id,
        beams_by_id=catalog_context.beams_by_id,
        torpedos_by_id=catalog_context.torpedos_by_id,
        buildable_hull_ids=catalog_context.buildable_hull_ids,
        eligible_engine_ids=catalog_context.eligible_engine_ids,
        eligible_beam_ids=catalog_context.eligible_beam_ids,
        eligible_torp_ids=catalog_context.eligible_torp_ids,
        prior_catalog=prior_catalog,
        turn=turn,
        player=player,
        policy_step=policy_step,
        policy_step_index=policy_step_index,
        policy_steps=resolve_tier_policies(),
    )
    asset_path = prior_catalog.diagnostics.asset_path if prior_catalog.diagnostics else ""
    return catalog.ship_build_combos, asset_path


def collisions_for_race(
    turn: TurnInfo,
    race_id: int,
    *,
    early_step: InferenceTierPolicyStep,
    widen_step: InferenceTierPolicyStep,
    early_step_index: int,
    widen_step_index: int,
    early_stop_min_plausibility: int,
    prior_weights_base_dir: Path | None = None,
) -> RaceCollisionReport | None:
    player = _player_for_race(turn, race_id)
    if player is None:
        return None

    hulls_by_id = {hull.id: hull for hull in turn.hulls}
    early_combos, _ = _build_catalog_for_step(
        turn,
        player,
        early_step,
        policy_step_index=early_step_index,
        prior_weights_base_dir=prior_weights_base_dir,
    )
    widen_combos, _ = _build_catalog_for_step(
        turn,
        player,
        widen_step,
        policy_step_index=widen_step_index,
        prior_weights_base_dir=prior_weights_base_dir,
    )

    mask = resolve_hull_catalog_mask(turn, player.id, user_enabled_hull_ids=None)
    early_ctx = turn_catalog_context_for_policy_step(
        turn, player.id, early_step, resolved_mask=mask
    )
    widen_ctx = turn_catalog_context_for_policy_step(
        turn, player.id, widen_step, resolved_mask=mask
    )
    early_hull_ids = early_ctx.buildable_hull_ids
    high_tech_hull_ids = widen_ctx.buildable_hull_ids - early_hull_ids

    early_warships = _single_warship_combos(early_combos)
    widen_warships = _single_warship_combos(widen_combos)
    if not early_warships:
        return RaceCollisionReport(
            race_id=race_id,
            race_name=mask.race_name,
            early_combo_count=len(early_combos),
            widen_combo_count=len(widen_combos),
            early_trigger_score_count=0,
            collisions=(),
            allowlist_hull_ids=(),
        )

    # Match solver: penalty is relative to max weight over the whole early catalog.
    max_early_weight = max(combo.probability_weight for combo in early_combos)
    early_by_score: dict[int, list[ComboRef]] = defaultdict(list)
    for combo in early_warships:
        if combo.hull_id not in early_hull_ids:
            continue
        objective = ship_only_objective(
            combo.probability_weight,
            max_combo_weight=max_early_weight,
        )
        if objective < early_stop_min_plausibility:
            continue
        hull = hulls_by_id[combo.hull_id]
        early_by_score[combo.score_delta_2x].append(
            _combo_ref(
                combo,
                hull_name=hull.name,
                hull_techlevel=hull.techlevel,
                ship_only_objective_value=objective,
            )
        )

    high_by_score: dict[int, list[ComboRef]] = defaultdict(list)
    for combo in widen_warships:
        if combo.hull_id not in high_tech_hull_ids:
            continue
        hull = hulls_by_id[combo.hull_id]
        high_by_score[combo.score_delta_2x].append(
            _combo_ref(
                combo,
                hull_name=hull.name,
                hull_techlevel=hull.techlevel,
            )
        )

    collisions: list[ScoreCollision] = []
    allowlist: set[int] = set()
    for score_delta_2x, early_members in sorted(early_by_score.items()):
        high_members = high_by_score.get(score_delta_2x)
        if not high_members:
            continue
        early_sorted = tuple(
            sorted(
                early_members,
                key=lambda member: (-(member.ship_only_objective or 0), member.combo_id),
            )
        )
        high_sorted = tuple(sorted(high_members, key=lambda member: member.combo_id))
        collisions.append(
            ScoreCollision(
                race_id=race_id,
                race_name=mask.race_name,
                military_change=score_delta_2x // 2,
                score_delta_2x=score_delta_2x,
                early_trigger_members=early_sorted,
                high_tech_members=high_sorted,
            )
        )
        allowlist.update(member.hull_id for member in high_sorted)

    return RaceCollisionReport(
        race_id=race_id,
        race_name=mask.race_name,
        early_combo_count=len(early_combos),
        widen_combo_count=len(widen_combos),
        early_trigger_score_count=len(early_by_score),
        collisions=tuple(collisions),
        allowlist_hull_ids=tuple(sorted(allowlist)),
    )


def run_collision_census(
    turn: TurnInfo,
    *,
    game_type: GameCategory,
    catalog_game_id: int,
    catalog_host_turn: int,
    catalog_perspective: int,
    catalog_native_game_type: GameCategory | None = None,
    race_ids: tuple[int, ...] | None = None,
    prior_weights_base_dir: Path | None = None,
    early_stop_min_plausibility: int | None = None,
) -> CollisionCensus:
    native = catalog_native_game_type or GameCategory.from_game_settings(
        turn.settings,
        player_count=len(turn.players),
    )
    coerced_settings = coerce_settings_for_category(turn.settings, game_type)
    turn = replace(turn, settings=coerced_settings)

    # Prior resolution uses settings shape only (no player-count gate).
    shaped = GameCategory.from_game_settings(turn.settings)
    if shaped != game_type:
        raise ValueError(
            f"settings coerce produced category {shaped.value!r}, expected {game_type.value!r}"
        )

    policy_steps = resolve_tier_policies()
    early_step = policy_steps[0]
    widen_step = first_full_hulls_policy_step(policy_steps)
    widen_step_index = next(
        index for index, step in enumerate(policy_steps) if step.id == widen_step.id
    )
    threshold = (
        early_stop_min_plausibility
        if early_stop_min_plausibility is not None
        else resolve_solver_thresholds().ship_only_exact_early_stop_min_plausibility
    )

    available_race_ids = sorted({player.raceid for player in turn.players if player.raceid > 0})
    if race_ids is None:
        selected_race_ids = tuple(available_race_ids)
    else:
        missing = [race_id for race_id in race_ids if race_id not in available_race_ids]
        if missing:
            raise ValueError(
                f"race id(s) {missing} not present on catalog turn players; "
                f"available: {available_race_ids}"
            )
        selected_race_ids = race_ids

    # Probe prior asset path once (may fall back to standard for blitz/missing files).
    probe_player = _player_for_race(turn, selected_race_ids[0])
    if probe_player is None:
        raise ValueError("no players available for selected races")
    _, prior_asset_path = _build_catalog_for_step(
        turn,
        probe_player,
        early_step,
        policy_step_index=0,
        prior_weights_base_dir=prior_weights_base_dir,
    )
    expected_stem = f"prior_weights_{game_type.value}"
    fell_back = Path(prior_asset_path).stem != expected_stem

    race_reports: list[RaceCollisionReport] = []
    allowlist_ids: set[int] = set()
    hulls_by_id = {hull.id: hull for hull in turn.hulls}
    for race_id in selected_race_ids:
        report = collisions_for_race(
            turn,
            race_id,
            early_step=early_step,
            widen_step=widen_step,
            early_step_index=0,
            widen_step_index=widen_step_index,
            early_stop_min_plausibility=threshold,
            prior_weights_base_dir=prior_weights_base_dir,
        )
        if report is None:
            continue
        race_reports.append(report)
        allowlist_ids.update(report.allowlist_hull_ids)

    allowlist_sorted = tuple(sorted(allowlist_ids))
    allowlist_hulls = tuple(
        (
            hull_id,
            hulls_by_id[hull_id].name if hull_id in hulls_by_id else "?",
            hulls_by_id[hull_id].techlevel if hull_id in hulls_by_id else -1,
        )
        for hull_id in allowlist_sorted
    )

    return CollisionCensus(
        game_type=game_type.value,
        prior_asset_path=prior_asset_path,
        prior_fell_back_to_standard=fell_back,
        catalog_game_id=catalog_game_id,
        catalog_host_turn=catalog_host_turn,
        catalog_perspective=catalog_perspective,
        catalog_native_game_type=native.value,
        early_stop_min_plausibility=threshold,
        early_policy_step_id=early_step.id,
        widen_hulls_policy_step_id=widen_step.id,
        races=tuple(race_reports),
        allowlist_hull_ids=allowlist_sorted,
        allowlist_hulls=allowlist_hulls,
    )


def load_catalog_turn(
    storage_root: Path,
    game_id: int,
    *,
    host_turn: int,
    perspective: int | None,
) -> tuple[TurnInfo, int, GameCategory]:
    info_path = storage_root / "games" / str(game_id) / "info.json"
    if not info_path.is_file():
        raise FileNotFoundError(f"missing game info: {info_path}")
    info_raw = json.loads(info_path.read_text())
    game_info = game_info_from_json(info_raw)
    native_category = GameCategory.from_game_info(game_info)
    settings_defaults = info_raw.get("settings")
    game_dir = storage_root / "games" / str(game_id)
    if perspective is None:
        slot_dirs = sorted(
            path
            for path in game_dir.iterdir()
            if path.is_dir() and path.name.isdigit() and (path / "turns").is_dir()
        )
        if not slot_dirs:
            raise FileNotFoundError(f"no perspective turn dirs under {game_dir}")
        perspective_slot = int(slot_dirs[0].name)
    else:
        perspective_slot = perspective
    turn_path = game_dir / str(perspective_slot) / "turns" / f"{host_turn}.json"
    if not turn_path.is_file():
        raise FileNotFoundError(f"missing turn file: {turn_path}")
    turn = turn_info_from_json(
        json.loads(turn_path.read_text()),
        settings_defaults=settings_defaults,
    )
    return turn, perspective_slot, native_category


def find_game_id_for_category(storage_root: Path, category: GameCategory) -> int:
    games_root = storage_root / "games"
    if not games_root.is_dir():
        raise FileNotFoundError(f"storage games root not found: {games_root}")
    matches: list[int] = []
    for info_path in sorted(games_root.glob("*/info.json")):
        try:
            game_id = int(info_path.parent.name)
        except ValueError:
            continue
        info = game_info_from_json(json.loads(info_path.read_text()))
        if GameCategory.from_game_info(info) == category:
            matches.append(game_id)
    if not matches:
        raise FileNotFoundError(
            f"no stored game with category {category.value!r} under {games_root}"
        )
    return matches[0]


def format_census_text(census: CollisionCensus) -> str:
    lines: list[str] = [
        f"game_type={census.game_type}",
        f"prior_asset={census.prior_asset_path}"
        + (" (fell back to standard)" if census.prior_fell_back_to_standard else ""),
        (
            f"catalog=game {census.catalog_game_id} turn {census.catalog_host_turn} "
            f"perspective {census.catalog_perspective} "
            f"(native_game_type={census.catalog_native_game_type})"
        ),
        f"early_stop_min_plausibility={census.early_stop_min_plausibility}",
        (
            f"early_step={census.early_policy_step_id} "
            f"widen_hulls_step={census.widen_hulls_policy_step_id}"
        ),
    ]
    if census.catalog_native_game_type != census.game_type:
        lines.append(
            "warning: catalog game native type differs from --game-type; "
            "hull/component lists come from the catalog game, priors from --game-type"
        )
    lines.extend(
        [
            "",
            f"Suggested early-tier hull allowlist ({len(census.allowlist_hull_ids)} hulls):",
        ]
    )
    if not census.allowlist_hulls:
        lines.append("  (empty)")
    else:
        for hull_id, name, techlevel in census.allowlist_hulls:
            lines.append(f"  {hull_id}: {name} (tech {techlevel})")

    total_collisions = sum(len(race.collisions) for race in census.races)
    lines.extend(["", f"Collisions ({total_collisions} score values across races):"])
    if total_collisions == 0:
        lines.append("  (none)")
        return "\n".join(lines)

    for race in census.races:
        if not race.collisions:
            continue
        lines.append("")
        lines.append(
            f"Race {race.race_id} {race.race_name}: "
            f"{len(race.collisions)} collision scores; "
            f"allowlist hulls={list(race.allowlist_hull_ids)}"
        )
        for collision in race.collisions:
            lines.append(
                f"  military_change={collision.military_change} "
                f"(score_delta_2x={collision.score_delta_2x})"
            )
            lines.append("    early triggers:")
            for member in collision.early_trigger_members:
                lines.append(
                    f"      obj={member.ship_only_objective} weight={member.probability_weight} "
                    f"| {member.label}"
                )
            lines.append("    high-tech twins:")
            for member in collision.high_tech_members:
                lines.append(
                    f"      hull_tech={member.hull_techlevel} weight={member.probability_weight} "
                    f"| {member.label}"
                )
    return "\n".join(lines)


def census_to_jsonable(census: CollisionCensus) -> dict[str, object]:
    return asdict(census)


def twin_triples_from_census(census: CollisionCensus) -> tuple[HullCollisionTwinTriple, ...]:
    """Expand census collisions into distinct (low, high, military_change) triples."""
    triples: dict[tuple[int, int, int], HullCollisionTwinTriple] = {}
    for race in census.races:
        for collision in race.collisions:
            low_hull_ids = {member.hull_id for member in collision.early_trigger_members}
            high_hull_ids = {member.hull_id for member in collision.high_tech_members}
            for low_hull_id in low_hull_ids:
                for high_hull_id in high_hull_ids:
                    key = (low_hull_id, high_hull_id, collision.military_change)
                    triples[key] = HullCollisionTwinTriple(
                        low_hull_id=low_hull_id,
                        high_hull_id=high_hull_id,
                        military_change=collision.military_change,
                    )
    return tuple(
        sorted(
            triples.values(),
            key=lambda triple: (
                triple.low_hull_id,
                triple.high_hull_id,
                triple.military_change,
            ),
        )
    )


def twins_asset_from_census(census: CollisionCensus) -> HullCollisionTwinsAsset:
    """Build a writeable twin asset from a full-race collision census."""
    category = parse_game_type(census.game_type)
    return build_twins_asset(
        category=category,
        triples=twin_triples_from_census(census),
        provenance=HullCollisionTwinsProvenance(
            catalog_game_id=census.catalog_game_id,
            catalog_host_turn=census.catalog_host_turn,
            catalog_perspective=census.catalog_perspective,
            early_policy_step_id=census.early_policy_step_id,
            widen_hulls_policy_step_id=census.widen_hulls_policy_step_id,
            early_stop_min_plausibility=census.early_stop_min_plausibility,
            prior_asset_stem=Path(census.prior_asset_path).stem,
        ),
    )


@app.command()
def main(
    game_type: str = typer.Option(
        ...,
        "--game-type",
        help=f"Prior/game category: {', '.join(GAME_TYPE_CHOICES)}",
    ),
    race: int | None = typer.Option(
        None,
        "--race",
        help="Race id to analyze. Omit to analyze every race present on the catalog turn.",
    ),
    game_id: int | None = typer.Option(
        None,
        "--game-id",
        help=(
            "Stored game providing the component/hull catalog. "
            "Omit to pick the first game under storage matching --game-type."
        ),
    ),
    host_turn: int = typer.Option(
        5,
        "--host-turn",
        help="Host turn number for the catalog snapshot.",
    ),
    perspective: int | None = typer.Option(
        None,
        "--perspective",
        help="Perspective slot under storage. Default: first available slot.",
    ),
    storage_root: Path = typer.Option(
        _default_storage_root(),
        "--storage-root",
        help="File backend root (default: ./.data).",
    ),
    prior_weights_dir: Path | None = typer.Option(
        None,
        "--prior-weights-dir",
        help=f"Prior assets directory (default: {default_prior_weights_dir()}).",
    ),
    early_stop_min_plausibility: int | None = typer.Option(
        None,
        "--early-stop-min-plausibility",
        help="Override tier-policy shipOnlyExactEarlyStopMinPlausibility.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON instead of text.",
    ),
    write_asset: bool = typer.Option(
        False,
        "--write-asset",
        help=(
            "Write hull_collision_twins_{game_type}.yaml under --asset-dir "
            f"(default: {default_twin_assets_dir()}). Requires a full-race census "
            "(do not pass --race)."
        ),
    ),
    asset_dir: Path | None = typer.Option(
        None,
        "--asset-dir",
        help=(f"Directory for --write-asset output (default: {default_twin_assets_dir()})."),
    ),
) -> None:
    try:
        category = parse_game_type(game_type)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    if write_asset and race is not None:
        typer.echo("--write-asset requires a full-race census; omit --race.", err=True)
        raise typer.Exit(code=2)

    if not storage_root.is_dir():
        typer.echo(f"storage root not found: {storage_root}", err=True)
        raise typer.Exit(code=2)

    try:
        resolved_game_id = (
            game_id if game_id is not None else find_game_id_for_category(storage_root, category)
        )
        turn, perspective_slot, native_category = load_catalog_turn(
            storage_root,
            resolved_game_id,
            host_turn=host_turn,
            perspective=perspective,
        )
        race_ids = (race,) if race is not None else None
        census = run_collision_census(
            turn,
            game_type=category,
            catalog_game_id=resolved_game_id,
            catalog_host_turn=host_turn,
            catalog_perspective=perspective_slot,
            catalog_native_game_type=native_category,
            race_ids=race_ids,
            prior_weights_base_dir=prior_weights_dir,
            early_stop_min_plausibility=early_stop_min_plausibility,
        )
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    if write_asset:
        try:
            asset = twins_asset_from_census(census)
            out_path = default_twin_asset_path(category, base_dir=asset_dir)
            write_hull_collision_twins_asset(out_path, asset)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(
            f"wrote {out_path} ({len(asset.triples)} triples)",
            err=True,
        )

    if json_output:
        typer.echo(json.dumps(census_to_jsonable(census), indent=2, sort_keys=True))
    else:
        typer.echo(format_census_text(census))


if __name__ == "__main__":
    app()
