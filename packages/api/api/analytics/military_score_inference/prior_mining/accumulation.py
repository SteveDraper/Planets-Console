"""Count accumulation for inference prior mining."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from api.analytics.military_score_inference.hull_category import InferenceHullCategory
from api.analytics.military_score_inference.prior_weights_asset import ShipLimitBand

from .observations import (
    PlayerHostTurnExtraction,
    ShipBuildObservation,
    record_ship_build_slot_fill_from_observation,
)


@dataclass
class AggregateActionTally:
    zero: int = 0
    positive: int = 0


def _nested_category_hull_counts() -> dict[str, dict[int, float]]:
    return defaultdict(lambda: defaultdict(float))


def _nested_race_category_hull_counts() -> dict[str, dict[str, dict[int, float]]]:
    return defaultdict(_nested_category_hull_counts)


def _nested_component_counts() -> dict[str, dict[str, dict[str | int, float]]]:
    return defaultdict(lambda: defaultdict(lambda: defaultdict(float)))


def _nested_aggregate_histograms() -> dict[str, dict[int, float]]:
    return defaultdict(lambda: defaultdict(float))


@dataclass
class PriorMiningAccumulation:
    hull_counts: dict[ShipLimitBand, dict[str, dict[str, dict[int, float]]]] = field(
        default_factory=lambda: defaultdict(_nested_race_category_hull_counts)
    )
    component_counts: dict[ShipLimitBand, dict[str, dict[str, dict[str | int, float]]]] = field(
        default_factory=lambda: defaultdict(_nested_component_counts)
    )
    aggregate_histograms: dict[ShipLimitBand, dict[str, dict[int, float]]] = field(
        default_factory=lambda: defaultdict(_nested_aggregate_histograms)
    )
    aggregate_tallies: dict[str, AggregateActionTally] = field(
        default_factory=lambda: defaultdict(AggregateActionTally)
    )

    def add_player_host_turn(
        self,
        extraction: PlayerHostTurnExtraction,
    ) -> None:
        for ship_build in extraction.ship_builds:
            self.add_ship_build(ship_build)
        band = extraction.ship_limit_band
        for action_id, delta in extraction.aggregate_deltas.items():
            self.add_aggregate_sample(action_id, band, delta)

    def add_ship_build(self, observation: ShipBuildObservation) -> None:
        band = observation.ship_limit_band
        race_key = str(observation.race_id)
        category: InferenceHullCategory = observation.hull_category  # type: ignore[assignment]
        self.hull_counts[band]["global"][category][observation.hull_id] += 1
        self.hull_counts[band][race_key][category][observation.hull_id] += 1

        category_tables = self.component_counts[band][category]
        engines = category_tables.setdefault("engines", defaultdict(float))
        beams = category_tables.setdefault("beams", defaultdict(float))
        torpedoes = category_tables.setdefault("torpedoes", defaultdict(float))
        slot_fill = category_tables.setdefault("slotFill", defaultdict(float))

        engines[observation.engine_id] += 1
        if observation.beam_count > 0:
            beams[observation.beam_id] += 1
        if observation.launcher_count > 0:
            torpedoes[observation.torpedo_id] += 1
        fill = record_ship_build_slot_fill_from_observation(observation)
        if fill is not None:
            slot_fill[fill] += 1

    def add_aggregate_sample(self, action_id: str, band: ShipLimitBand, delta: int) -> None:
        histogram_key = 0 if delta <= 0 else delta
        if action_id in ("fighters_starbase_to_ship", "fighters_ship_to_starbase"):
            histogram_key = 1 if delta > 0 else 0
        self.aggregate_histograms[band][action_id][histogram_key] += 1
        tally = self.aggregate_tallies[action_id]
        if histogram_key == 0:
            tally.zero += 1
        else:
            tally.positive += 1

    def merge(self, other: PriorMiningAccumulation) -> None:
        for band, race_tables in other.hull_counts.items():
            for race_key, category_tables in race_tables.items():
                for category, hull_table in category_tables.items():
                    target = self.hull_counts[band][race_key][category]
                    for hull_id, count in hull_table.items():
                        target[hull_id] += count

        for band, categories in other.component_counts.items():
            for category, tables in categories.items():
                target_tables = self.component_counts[band][category]
                for table_name, counts in tables.items():
                    target_table = target_tables.setdefault(table_name, defaultdict(float))
                    for key, count in counts.items():
                        target_table[key] += count

        for band, actions in other.aggregate_histograms.items():
            for action_id, histogram in actions.items():
                for magnitude, count in histogram.items():
                    self.aggregate_histograms[band][action_id][magnitude] += count

        for action_id, tally in other.aggregate_tallies.items():
            target = self.aggregate_tallies[action_id]
            target.zero += tally.zero
            target.positive += tally.positive
