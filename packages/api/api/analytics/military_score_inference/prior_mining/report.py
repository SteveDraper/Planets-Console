"""JSON report models for inference prior mining."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .accumulation import AggregateActionTally, PriorMiningAccumulation
from .discovery import PatternDiscoveryResult
from .merge import accumulation_mining_report_sections


@dataclass
class IncompleteLoadAllDetail:
    game_id: int
    gaps: list[dict[str, object]] = field(default_factory=list)


@dataclass
class ExtractionErrorDetail:
    game_id: int
    player_id: int
    host_turn: int
    message: str


@dataclass
class GameMiningErrorDetail:
    game_id: int
    message: str


@dataclass
class PatternReport:
    pattern_id: str
    game_category: str
    candidates_examined: int
    category_mismatches: int
    already_contributed: int
    games_attempted: tuple[int, ...]
    games_rejected: tuple[int, ...]
    games_added: tuple[int, ...]
    slots_remaining: int


@dataclass
class PriorMiningReport:
    dry_run: bool
    debug: bool = False
    patterns: list[PatternReport] = field(default_factory=list)
    games_skipped_incomplete_loadall: int = 0
    incomplete_loadall_details: list[IncompleteLoadAllDetail] = field(default_factory=list)
    adjunct_skips: int = 0
    ship_build_validation_drops: int = 0
    extraction_errors: list[ExtractionErrorDetail] = field(default_factory=list)
    game_mining_errors: list[GameMiningErrorDetail] = field(default_factory=list)
    aborted: bool = False
    abort_message: str | None = None
    ship_builds: dict[str, Any] = field(default_factory=dict)
    aggregate_histograms: dict[str, Any] = field(default_factory=dict)
    aggregate_action_tallies: dict[str, AggregateActionTally] = field(default_factory=dict)
    merged_categories: list[str] = field(default_factory=list)
    written_assets: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["aggregate_action_tallies"] = {
            action_id: {"zero": tally.zero, "positive": tally.positive}
            for action_id, tally in self.aggregate_action_tallies.items()
        }
        return payload

    def to_summary_dict(self) -> dict[str, Any]:
        """Compact report for stdout: discovery stats plus count-table rollups only."""
        return {
            "dry_run": self.dry_run,
            "debug": self.debug,
            "patterns": [asdict(pattern) for pattern in self.patterns],
            "games_skipped_incomplete_loadall": self.games_skipped_incomplete_loadall,
            "incomplete_loadall_details": [
                asdict(detail) for detail in self.incomplete_loadall_details
            ],
            "adjunct_skips": self.adjunct_skips,
            "ship_build_validation_drops": self.ship_build_validation_drops,
            "extraction_errors": [asdict(error) for error in self.extraction_errors],
            "game_mining_errors": [asdict(error) for error in self.game_mining_errors],
            "aborted": self.aborted,
            "abort_message": self.abort_message,
            "ship_builds": _summarize_ship_builds_section(self.ship_builds),
            "aggregate_histograms": _summarize_aggregate_histogram_section(
                self.aggregate_histograms
            ),
            "aggregate_action_tallies": {
                action_id: {"zero": tally.zero, "positive": tally.positive}
                for action_id, tally in self.aggregate_action_tallies.items()
            },
            "merged_categories": list(self.merged_categories),
            "written_assets": list(self.written_assets),
        }

    def to_summary_json(self) -> str:
        return json.dumps(self.to_summary_dict(), indent=2, sort_keys=True)


def merge_accumulation_into_report(
    report: PriorMiningReport,
    accumulation: PriorMiningAccumulation,
) -> None:
    """Add mined hull, component, and aggregate histogram counts to the report."""
    sections = accumulation_mining_report_sections(accumulation)
    report.ship_builds = _merge_ship_build_sections(report.ship_builds, sections)
    report.aggregate_histograms = _merge_aggregate_histogram_sections(
        report.aggregate_histograms,
        sections["aggregate_histograms"],
    )
    for action_id, tally in accumulation.aggregate_tallies.items():
        target = report.aggregate_action_tallies.setdefault(action_id, AggregateActionTally())
        target.zero += tally.zero
        target.positive += tally.positive


def _merge_ship_build_sections(
    existing: dict[str, Any], sections: dict[str, Any]
) -> dict[str, Any]:
    merged = dict(existing)
    merged["total_ship_builds"] = merged.get("total_ship_builds", 0) + sections["total_ship_builds"]
    merged["hulls"] = _merge_nested_count_tables(merged.get("hulls", {}), sections["hulls"])
    merged["components"] = _merge_nested_count_tables(
        merged.get("components", {}),
        sections["components"],
    )
    return merged


def _merge_aggregate_histogram_sections(
    existing: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    merged: dict[str, Any] = {band: dict(existing.get(band, {})) for band in incoming}
    for band, actions in incoming.items():
        band_target = merged.setdefault(band, {})
        for action_id, payload in actions.items():
            histogram = payload.get("histogram", {})
            action_target = band_target.setdefault(action_id, {"histogram": {}})
            target_histogram = action_target.setdefault("histogram", {})
            for magnitude, count in histogram.items():
                target_histogram[magnitude] = target_histogram.get(magnitude, 0) + count
    return merged


def _merge_nested_count_tables(
    existing: dict[str, Any], incoming: dict[str, Any]
) -> dict[str, Any]:
    if not existing:
        return incoming
    if not incoming:
        return existing
    merged: dict[str, Any] = {}
    for band in set(existing) | set(incoming):
        merged[band] = _merge_count_table_node(existing.get(band, {}), incoming.get(band, {}))
    return merged


def _merge_count_table_node(existing: object, incoming: object) -> object:
    if not isinstance(existing, dict):
        return incoming
    if not isinstance(incoming, dict):
        return existing
    merged: dict[str, Any] = {}
    for key in set(existing) | set(incoming):
        existing_value = existing.get(key)
        incoming_value = incoming.get(key)
        if isinstance(existing_value, dict) and isinstance(incoming_value, dict):
            if all(
                isinstance(v, dict) for v in (*existing_value.values(), *incoming_value.values())
            ):
                merged[key] = _merge_nested_count_tables(existing_value, incoming_value)
            elif all(
                not isinstance(v, dict)
                for v in (*existing_value.values(), *incoming_value.values())
            ):
                merged[key] = _merge_count_table_node(existing_value, incoming_value)
            else:
                merged[key] = _merge_count_table_node(existing_value, incoming_value)
        elif isinstance(existing_value, (int, float)) and isinstance(incoming_value, (int, float)):
            merged[key] = existing_value + incoming_value
        elif existing_value is None:
            merged[key] = incoming_value
        elif incoming_value is None:
            merged[key] = existing_value
        else:
            merged[key] = incoming_value
    return merged


def pattern_report_from_discovery(discovery: PatternDiscoveryResult) -> PatternReport:
    return PatternReport(
        pattern_id=discovery.pattern_id,
        game_category=discovery.game_category.value,
        candidates_examined=discovery.candidates_examined,
        category_mismatches=discovery.category_mismatches,
        already_contributed=discovery.already_contributed,
        games_attempted=discovery.games_attempted,
        games_rejected=discovery.games_rejected,
        games_added=discovery.games_added,
        slots_remaining=discovery.slots_remaining,
    )


def _summarize_ship_builds_section(section: dict[str, Any]) -> dict[str, Any]:
    if not section:
        return {}
    summary: dict[str, Any] = {}
    if "total_ship_builds" in section:
        summary["total_ship_builds"] = section["total_ship_builds"]
    hulls = section.get("hulls")
    if isinstance(hulls, dict) and hulls:
        summary["hulls"] = {
            band: _summarize_count_tree(band_tables) for band, band_tables in hulls.items()
        }
    components = section.get("components")
    if isinstance(components, dict) and components:
        summary["components"] = {
            band: _summarize_count_tree(band_tables) for band, band_tables in components.items()
        }
    return summary


def _summarize_aggregate_histogram_section(section: dict[str, Any]) -> dict[str, Any]:
    if not section:
        return {}
    summarized: dict[str, Any] = {}
    for band, actions in section.items():
        if not isinstance(actions, dict):
            continue
        band_summary: dict[str, Any] = {}
        for action_id, payload in actions.items():
            if not isinstance(payload, dict):
                continue
            histogram = payload.get("histogram")
            if not isinstance(histogram, dict):
                continue
            band_summary[action_id] = _summarize_leaf_counts(histogram)
        summarized[band] = band_summary
    return summarized


def _summarize_count_tree(node: object) -> dict[str, int | float]:
    unique_keys, sample_count = _leaf_stats_from_count_tree(node)
    return {
        "unique_keys": len(unique_keys),
        "sample_count": _normalize_sample_count(sample_count),
    }


def _summarize_leaf_counts(counts: dict[Any, float]) -> dict[str, int | float]:
    return {
        "unique_keys": len(counts),
        "sample_count": _normalize_sample_count(sum(counts.values())),
    }


def _normalize_sample_count(value: float) -> int | float:
    if value == int(value):
        return int(value)
    return value


def _leaf_stats_from_count_tree(node: object, *, path_prefix: str = "") -> tuple[set[str], float]:
    if not isinstance(node, dict) or not node:
        return set(), 0.0
    if all(isinstance(value, (int, float)) for value in node.values()):
        keys = {f"{path_prefix}/{key}" if path_prefix else str(key) for key in node}
        return keys, float(sum(node.values()))
    unique_keys: set[str] = set()
    sample_count = 0.0
    for key, value in node.items():
        child_prefix = f"{path_prefix}/{key}" if path_prefix else str(key)
        child_keys, child_count = _leaf_stats_from_count_tree(value, path_prefix=child_prefix)
        unique_keys |= child_keys
        sample_count += child_count
    return unique_keys, sample_count
