"""Mine-stock observation family for the inference prior miner (#398).

Owner-perspective snapshot of total mine units and field count, partitioned
game category x race x host turn. Sibling asset ``mine_stock_{category}.yaml``.
Does not convert units to military points or split by nebula.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from api.analytics.scores_assets import Scores
from api.concepts.game_category import GAME_CATEGORY_RULES_VERSION, GameCategory
from api.models.game import TurnInfo
from api.models.space import Minefield

MINE_STOCK_ASSET_VERSION = 1

MINE_STOCK_HISTOGRAM_KEYS: tuple[str, ...] = (
    "totalUnits",
    "fieldCount",
    "perFieldUnits",
    "webTotalUnits",
    "webFieldCount",
    "webPerFieldUnits",
    "normalTotalUnits",
    "normalFieldCount",
    "normalPerFieldUnits",
)

_TOTAL_KEYS = frozenset(
    {
        "totalUnits",
        "fieldCount",
        "webTotalUnits",
        "webFieldCount",
        "normalTotalUnits",
        "normalFieldCount",
    }
)


@dataclass(frozen=True)
class MineStockHistogramSpec:
    yaml_key: str
    total_attr: str | None
    values_attr: str | None


MINE_STOCK_HISTOGRAM_SPECS: tuple[MineStockHistogramSpec, ...] = (
    MineStockHistogramSpec("totalUnits", "total_units", None),
    MineStockHistogramSpec("fieldCount", "field_count", None),
    MineStockHistogramSpec("perFieldUnits", None, "per_field_units"),
    MineStockHistogramSpec("webTotalUnits", "web_total_units", None),
    MineStockHistogramSpec("webFieldCount", "web_field_count", None),
    MineStockHistogramSpec("webPerFieldUnits", None, "web_per_field_units"),
    MineStockHistogramSpec("normalTotalUnits", "normal_total_units", None),
    MineStockHistogramSpec("normalFieldCount", "normal_field_count", None),
    MineStockHistogramSpec("normalPerFieldUnits", None, "normal_per_field_units"),
)


def _nested_turn_histograms() -> dict[int, dict[str, dict[int, float]]]:
    return defaultdict(lambda: defaultdict(lambda: defaultdict(float)))


MineStockHistograms = dict[int, dict[int, dict[str, dict[int, float]]]]


@dataclass(frozen=True)
class MineStockSample:
    """One owner-perspective mine-stock snapshot at a single host turn."""

    race_id: int
    host_turn: int
    total_units: int
    field_count: int
    per_field_units: tuple[int, ...]
    web_total_units: int
    web_field_count: int
    web_per_field_units: tuple[int, ...]
    normal_total_units: int
    normal_field_count: int
    normal_per_field_units: tuple[int, ...]
    infoturn_mismatches: int


@dataclass
class MineStockAccumulation:
    histograms: MineStockHistograms = field(
        default_factory=lambda: defaultdict(_nested_turn_histograms)
    )
    sample_count: int = 0
    zero_stock_count: int = 0
    infoturn_mismatches: int = 0

    def add_sample(self, sample: MineStockSample) -> None:
        cell = self.histograms[sample.race_id][sample.host_turn]
        for spec in MINE_STOCK_HISTOGRAM_SPECS:
            if spec.total_attr is not None:
                magnitude = int(getattr(sample, spec.total_attr))
                cell[spec.yaml_key][magnitude] += 1
                continue
            values = getattr(sample, spec.values_attr) if spec.values_attr is not None else ()
            for magnitude in values:
                cell[spec.yaml_key][int(magnitude)] += 1
        self.sample_count += 1
        if sample.total_units == 0:
            self.zero_stock_count += 1
        self.infoturn_mismatches += sample.infoturn_mismatches

    def merge(self, other: MineStockAccumulation) -> None:
        for race_id, turns in other.histograms.items():
            for host_turn, histograms in turns.items():
                target_cell = self.histograms[race_id][host_turn]
                for yaml_key, counts in histograms.items():
                    target = target_cell[yaml_key]
                    for magnitude, count in counts.items():
                        target[magnitude] += count
        self.sample_count += other.sample_count
        self.zero_stock_count += other.zero_stock_count
        self.infoturn_mismatches += other.infoturn_mismatches

    def row_counts_by_race_turn(self) -> dict[int, dict[int, int]]:
        """Sample counts per (race, host turn); equals sum of ``totalUnits`` histogram."""
        return _row_counts_from_histograms(self.histograms)


@dataclass(frozen=True)
class MineStockAsset:
    version: int
    category: str
    game_category_rules_version: int
    histograms: MineStockHistograms
    contributing_game_ids: tuple[int, ...] = ()


def owned_active_minefields(turn: TurnInfo, player_id: int) -> tuple[Minefield, ...]:
    """Owner fields with ``units > 0`` (empty-stock samples have no members)."""
    return tuple(
        field for field in turn.minefields if field.ownerid == player_id and field.units > 0
    )


def extract_mine_stock_sample(
    turn: TurnInfo,
    *,
    player_id: int,
    race_id: int,
    host_turn: int,
) -> MineStockSample:
    """Snapshot total units and field count for one owner at ``host_turn``."""
    owned = owned_active_minefields(turn, player_id)
    web = tuple(field for field in owned if field.isweb)
    normal = tuple(field for field in owned if not field.isweb)
    infoturn_mismatches = sum(1 for field in owned if field.infoturn != host_turn)
    return MineStockSample(
        race_id=race_id,
        host_turn=host_turn,
        total_units=sum(field.units for field in owned),
        field_count=len(owned),
        per_field_units=tuple(field.units for field in owned),
        web_total_units=sum(field.units for field in web),
        web_field_count=len(web),
        web_per_field_units=tuple(field.units for field in web),
        normal_total_units=sum(field.units for field in normal),
        normal_field_count=len(normal),
        normal_per_field_units=tuple(field.units for field in normal),
        infoturn_mismatches=infoturn_mismatches,
    )


def mine_stock_path_for_category(category: GameCategory, *, base_dir: Path) -> Path:
    return base_dir / f"mine_stock_{category.value}.yaml"


def default_mine_stock_dir() -> Path:
    return Scores.assets_dir()


def create_empty_mine_stock_asset(category: GameCategory) -> MineStockAsset:
    return MineStockAsset(
        version=MINE_STOCK_ASSET_VERSION,
        category=category.value,
        game_category_rules_version=GAME_CATEGORY_RULES_VERSION,
        histograms={},
        contributing_game_ids=(),
    )


def load_or_empty_mine_stock_asset(
    category: GameCategory, *, base_dir: Path
) -> MineStockAsset | None:
    path = mine_stock_path_for_category(category, base_dir=base_dir)
    if not path.is_file():
        return None
    return load_mine_stock_asset(path)


def load_or_bootstrap_mine_stock_asset(category: GameCategory, *, base_dir: Path) -> MineStockAsset:
    existing = load_or_empty_mine_stock_asset(category, base_dir=base_dir)
    if existing is not None:
        return existing
    return create_empty_mine_stock_asset(category)


def load_mine_stock_asset(path: Path) -> MineStockAsset:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return parse_mine_stock_document(raw)


def parse_mine_stock_document(document: Mapping[str, Any]) -> MineStockAsset:
    version = document.get("version")
    if version != MINE_STOCK_ASSET_VERSION:
        raise ValueError(
            f"mine-stock asset version must be {MINE_STOCK_ASSET_VERSION}, got {version!r}"
        )
    category = document.get("category")
    if not isinstance(category, str) or not category:
        raise ValueError("mine-stock asset category must be a non-empty string")
    rules_version = document.get("gameCategoryRulesVersion")
    if not isinstance(rules_version, int):
        raise ValueError("mine-stock asset gameCategoryRulesVersion must be an integer")
    contributing = document.get("contributingGameIds", [])
    if contributing is None:
        contributing = []
    if not isinstance(contributing, list) or not all(
        isinstance(item, int) for item in contributing
    ):
        raise ValueError("mine-stock contributingGameIds must be a list of integers")
    # rowCounts is derived from totalUnits at write time and is not loaded.
    histograms = _parse_mine_stock_histograms(document.get("mineStock", {}))
    return MineStockAsset(
        version=MINE_STOCK_ASSET_VERSION,
        category=category,
        game_category_rules_version=rules_version,
        histograms=histograms,
        contributing_game_ids=tuple(contributing),
    )


def merge_mine_stock_accumulation_into_asset(
    asset: MineStockAsset,
    accumulation: MineStockAccumulation,
    *,
    provenance_game_ids: tuple[int, ...],
) -> MineStockAsset:
    merged_histograms = _deep_copy_histograms(asset.histograms)
    for race_id, turns in accumulation.histograms.items():
        for host_turn, histograms in turns.items():
            target_cell = merged_histograms.setdefault(race_id, {}).setdefault(host_turn, {})
            for yaml_key, counts in histograms.items():
                target = target_cell.setdefault(yaml_key, {})
                for magnitude, count in counts.items():
                    target[magnitude] = target.get(magnitude, 0.0) + count
    return MineStockAsset(
        version=MINE_STOCK_ASSET_VERSION,
        category=asset.category,
        game_category_rules_version=GAME_CATEGORY_RULES_VERSION,
        histograms=merged_histograms,
        contributing_game_ids=_merge_contributing_game_ids(
            asset.contributing_game_ids,
            provenance_game_ids,
        ),
    )


class _FlowHistogram(dict):
    """Leaf magnitude-to-count map; dumped as a compact YAML flow mapping."""


class _MineStockYamlDumper(yaml.SafeDumper):
    """SafeDumper that emits `_FlowHistogram` as a YAML flow mapping."""


def _represent_flow_histogram(
    dumper: yaml.SafeDumper, data: _FlowHistogram
) -> yaml.nodes.MappingNode:
    return dumper.represent_mapping("tag:yaml.org,2002:map", data, flow_style=True)


_MineStockYamlDumper.add_representer(_FlowHistogram, _represent_flow_histogram)


def write_mine_stock_asset(path: Path, asset: MineStockAsset) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = mine_stock_asset_to_document(asset)
    header = (
        f"# Mine-stock priors for inference game category {asset.category} (#398).\n"
        "# Owner-perspective histograms of total mine units and field count,\n"
        "# partitioned race x host turn. Raw integer keys; no decay conversion.\n"
        "#\n"
        "# Replay contributing games from prior_weights_{category}.yaml:\n"
        "#   uv run python scripts/run_inference_prior_miner.py \\\n"
        f"#     --patterns assets/analytics/scores/prior_mining_patterns_{asset.category}.yaml \\\n"
        "#     --replay-mine-stock\n"
        "#\n"
    )
    body = yaml.dump(
        document,
        Dumper=_MineStockYamlDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    path.write_text(header + body, encoding="utf-8")


def mine_stock_asset_to_document(asset: MineStockAsset) -> dict[str, Any]:
    document: dict[str, Any] = {
        "version": asset.version,
        "category": asset.category,
        "gameCategoryRulesVersion": asset.game_category_rules_version,
    }
    if asset.contributing_game_ids:
        document["contributingGameIds"] = list(asset.contributing_game_ids)
    document["rowCounts"] = _serialize_row_counts(asset.histograms)
    document["mineStock"] = _serialize_histograms(asset.histograms)
    return document


def accumulation_mine_stock_report_section(accumulation: MineStockAccumulation) -> dict[str, Any]:
    return {
        "sample_count": accumulation.sample_count,
        "zero_stock_count": accumulation.zero_stock_count,
        "infoturn_mismatches": accumulation.infoturn_mismatches,
        "row_counts": {
            str(race_id): {str(host_turn): count for host_turn, count in sorted(turns.items())}
            for race_id, turns in sorted(accumulation.row_counts_by_race_turn().items())
        },
    }


def _parse_mine_stock_histograms(raw: object) -> MineStockHistograms:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ValueError("mineStock must be a mapping")
    by_race_raw = raw.get("byRace", {})
    if not isinstance(by_race_raw, dict):
        raise ValueError("mineStock.byRace must be a mapping")
    histograms: MineStockHistograms = {}
    for race_key, race_payload in by_race_raw.items():
        race_id = _require_int_key(race_key, "mineStock.byRace")
        if not isinstance(race_payload, dict):
            raise ValueError(f"mineStock.byRace.{race_id} must be a mapping")
        by_turn_raw = race_payload.get("byTurn", {})
        if not isinstance(by_turn_raw, dict):
            raise ValueError(f"mineStock.byRace.{race_id}.byTurn must be a mapping")
        turns: dict[int, dict[str, dict[int, float]]] = {}
        for turn_key, cell_raw in by_turn_raw.items():
            host_turn = _require_int_key(turn_key, f"mineStock.byRace.{race_id}.byTurn")
            turns[host_turn] = _parse_histogram_cell(cell_raw, host_turn=host_turn, race_id=race_id)
        histograms[race_id] = turns
    return histograms


def _parse_histogram_cell(
    raw: object, *, host_turn: int, race_id: int
) -> dict[str, dict[int, float]]:
    if not isinstance(raw, dict):
        raise ValueError(f"mineStock cell race {race_id} turn {host_turn} must be a mapping")
    cell: dict[str, dict[int, float]] = {}
    for yaml_key in MINE_STOCK_HISTOGRAM_KEYS:
        payload = raw.get(yaml_key)
        if payload is None:
            continue
        if not isinstance(payload, dict):
            raise ValueError(f"{yaml_key} at race {race_id} turn {host_turn} must be a mapping")
        histogram_raw = payload.get("histogram", payload)
        if not isinstance(histogram_raw, dict):
            raise ValueError(
                f"{yaml_key}.histogram at race {race_id} turn {host_turn} must be a mapping"
            )
        counts: dict[int, float] = {}
        for magnitude_key, count in histogram_raw.items():
            magnitude = _require_int_key(magnitude_key, f"{yaml_key} histogram")
            if not isinstance(count, (int, float)) or count < 0:
                raise ValueError(f"{yaml_key} histogram values must be non-negative numbers")
            counts[magnitude] = float(count)
        if counts:
            cell[yaml_key] = counts
    return cell


def _row_counts_from_histograms(histograms: MineStockHistograms) -> dict[int, dict[int, int]]:
    rows: dict[int, dict[int, int]] = {}
    for race_id, turns in histograms.items():
        race_rows: dict[int, int] = {}
        for host_turn, cell in turns.items():
            total_units = cell.get("totalUnits", {})
            race_rows[host_turn] = int(sum(total_units.values()))
        if race_rows:
            rows[race_id] = race_rows
    return rows


def _serialize_row_counts(histograms: MineStockHistograms) -> dict[str, Any]:
    by_race: dict[int, Any] = {}
    for race_id, turns in sorted(_row_counts_from_histograms(histograms).items()):
        by_race[race_id] = {"byTurn": dict(sorted(turns.items()))}
    return {"byRace": by_race}


def _serialize_histograms(histograms: MineStockHistograms) -> dict[str, Any]:
    by_race: dict[int, Any] = {}
    for race_id in sorted(histograms):
        by_turn: dict[int, Any] = {}
        for host_turn in sorted(histograms[race_id]):
            cell_payload: dict[str, Any] = {}
            cell = histograms[race_id][host_turn]
            for yaml_key in MINE_STOCK_HISTOGRAM_KEYS:
                counts = cell.get(yaml_key, {})
                if not counts and yaml_key not in _TOTAL_KEYS:
                    continue
                if not counts:
                    continue
                cell_payload[yaml_key] = {
                    "histogram": _FlowHistogram(
                        (int(magnitude), _count_for_yaml(count))
                        for magnitude, count in sorted(counts.items())
                    )
                }
            if cell_payload:
                by_turn[host_turn] = cell_payload
        if by_turn:
            by_race[race_id] = {"byTurn": by_turn}
    return {"byRace": by_race}


def _count_for_yaml(count: float) -> int | float:
    if count == int(count):
        return int(count)
    return count


def _deep_copy_histograms(histograms: MineStockHistograms) -> MineStockHistograms:
    copied: MineStockHistograms = {}
    for race_id, turns in histograms.items():
        copied[race_id] = {
            host_turn: {yaml_key: dict(counts) for yaml_key, counts in cell.items()}
            for host_turn, cell in turns.items()
        }
    return copied


def _merge_contributing_game_ids(
    existing: tuple[int, ...], new_ids: tuple[int, ...]
) -> tuple[int, ...]:
    merged: list[int] = list(existing)
    seen = set(existing)
    for game_id in new_ids:
        if game_id in seen:
            continue
        merged.append(game_id)
        seen.add(game_id)
    return tuple(merged)


def _require_int_key(key: object, field_name: str) -> int:
    if isinstance(key, bool) or not isinstance(key, int):
        raise ValueError(f"{field_name} keys must be integers, got {key!r}")
    return key
