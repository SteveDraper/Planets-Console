"""Row-scoped reuse of scores catalog pieces that survive a rung change.

One store per policy-ladder state: one player, one turn. The store keeps the
ship-build combo tuple when the next rung has the same eligible sets and slot
mode, and keeps the individual ``ShipBuildCombo`` objects when the next rung
only adds combos. Prior-weight tables and the ship-transfer fragment are kept
when their own inputs match. Aggregate actions, probability buckets, and
admission caps are not stored here.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from api.analytics.fleet.types import FleetShipRecord
from api.analytics.military_score_inference.models import ShipBuildCombo
from api.analytics.military_score_inference.prior_weights_asset import ShipLimitBand
from api.analytics.military_score_inference.prior_weights_catalog import PriorWeightsCatalog
from api.analytics.military_score_inference.ship_transfer_families import (
    ShipTransferCatalogFragment,
)
from api.analytics.military_score_inference.tier_policy import SlotCountMode


def _slot_mode_covers(held: SlotCountMode, requested: SlotCountMode) -> bool:
    """True when every slot count ``held`` emits is also emitted by ``requested``."""
    if held == requested:
        return True
    return held == "none" and requested == "partial"


@dataclass(frozen=True)
class ShipBuildComboSpace:
    """Inputs that decide whether an existing combo tuple can be kept or extended."""

    buildable_hull_ids: frozenset[int]
    eligible_engine_ids: frozenset[int]
    eligible_beam_ids: frozenset[int]
    eligible_torp_ids: frozenset[int]
    beam_slot_counts: SlotCountMode
    launcher_slot_counts: SlotCountMode
    extra_warship_capacity: int
    extra_freighter_capacity: int
    reserved_incoming_warships: int
    reserved_incoming_freighters: int
    warship_delta: int
    freighter_delta: int
    starbases_owned: int
    military_delta_2x: int
    max_aggregate_residual_when_ship_builds: int | None

    def covers(self, earlier: ShipBuildComboSpace) -> bool:
        """True when every combo ``earlier`` could emit is still in this space.

        Transfer capacity and observation bounds stay equal: those values are
        baked into each combo, so a change invalidates the objects.
        """
        return (
            earlier.buildable_hull_ids <= self.buildable_hull_ids
            and earlier.eligible_engine_ids <= self.eligible_engine_ids
            and earlier.eligible_beam_ids <= self.eligible_beam_ids
            and earlier.eligible_torp_ids <= self.eligible_torp_ids
            and _slot_mode_covers(earlier.beam_slot_counts, self.beam_slot_counts)
            and _slot_mode_covers(earlier.launcher_slot_counts, self.launcher_slot_counts)
            and self._baked_bounds() == earlier._baked_bounds()
        )

    def _baked_bounds(self) -> tuple[int, int, int, int, int, int, int, int, int | None]:
        return (
            self.extra_warship_capacity,
            self.extra_freighter_capacity,
            self.reserved_incoming_warships,
            self.reserved_incoming_freighters,
            self.warship_delta,
            self.freighter_delta,
            self.starbases_owned,
            self.military_delta_2x,
            self.max_aggregate_residual_when_ship_builds,
        )


@dataclass
class CatalogReuseTotals:
    """Process-wide counts of ladder-rung catalog reuse.

    One tally for the process, not one shell. ``combo_initial_builds`` is the
    first combo tuple on a ladder state. ``combo_rebuild_calls`` is a later
    rung whose space does not cover the stored one, so the tuple is built
    again. ``combo_exact_hits`` returns the stored tuple. ``combo_extend_calls``
    builds with the stored objects offered as retained. Object counts are the
    combos in the tuple that rung kept: reused means the same object, allocated
    means a new one.
    """

    prior_hits: int = 0
    prior_builds: int = 0
    transfer_hits: int = 0
    transfer_builds: int = 0
    combo_initial_builds: int = 0
    combo_exact_hits: int = 0
    combo_extend_calls: int = 0
    combo_rebuild_calls: int = 0
    combo_objects_reused: int = 0
    combo_objects_allocated: int = 0


_totals_lock = threading.Lock()
_totals = CatalogReuseTotals()


def catalog_reuse_totals() -> CatalogReuseTotals:
    """Copy of the process-wide tally."""
    with _totals_lock:
        return CatalogReuseTotals(
            prior_hits=_totals.prior_hits,
            prior_builds=_totals.prior_builds,
            transfer_hits=_totals.transfer_hits,
            transfer_builds=_totals.transfer_builds,
            combo_initial_builds=_totals.combo_initial_builds,
            combo_exact_hits=_totals.combo_exact_hits,
            combo_extend_calls=_totals.combo_extend_calls,
            combo_rebuild_calls=_totals.combo_rebuild_calls,
            combo_objects_reused=_totals.combo_objects_reused,
            combo_objects_allocated=_totals.combo_objects_allocated,
        )


def reset_catalog_reuse_totals() -> None:
    """Zero the process-wide tally. Tests only."""
    global _totals
    with _totals_lock:
        _totals = CatalogReuseTotals()


def catalog_reuse_totals_wire() -> dict[str, int | bool]:
    """CamelCase tally for the compute diagnostics snapshot."""
    totals = catalog_reuse_totals()
    return {
        "processWide": True,
        "priorHits": totals.prior_hits,
        "priorBuilds": totals.prior_builds,
        "transferHits": totals.transfer_hits,
        "transferBuilds": totals.transfer_builds,
        "comboInitialBuilds": totals.combo_initial_builds,
        "comboExactHits": totals.combo_exact_hits,
        "comboExtendCalls": totals.combo_extend_calls,
        "comboRebuildCalls": totals.combo_rebuild_calls,
        "comboObjectsReused": totals.combo_objects_reused,
        "comboObjectsAllocated": totals.combo_objects_allocated,
    }


def _record_prior(*, hit: bool) -> None:
    with _totals_lock:
        if hit:
            _totals.prior_hits += 1
        else:
            _totals.prior_builds += 1


def _record_transfer(*, hit: bool) -> None:
    with _totals_lock:
        if hit:
            _totals.transfer_hits += 1
        else:
            _totals.transfer_builds += 1


def _record_combos(
    *,
    kind: str,
    reused: int,
    allocated: int,
) -> None:
    with _totals_lock:
        if kind == "exact":
            _totals.combo_exact_hits += 1
        elif kind == "extend":
            _totals.combo_extend_calls += 1
        elif kind == "rebuild":
            _totals.combo_rebuild_calls += 1
        else:
            _totals.combo_initial_builds += 1
        _totals.combo_objects_reused += reused
        _totals.combo_objects_allocated += allocated


def _combo_object_reuse(
    retained: tuple[ShipBuildCombo, ...] | None,
    combos: tuple[ShipBuildCombo, ...],
) -> tuple[int, int]:
    if not retained:
        return 0, len(combos)
    retained_ids = {id(combo) for combo in retained}
    reused = sum(1 for combo in combos if id(combo) in retained_ids)
    return reused, len(combos) - reused


class ScoresCatalogReuse:
    """Mutable reuse memory for one ladder state."""

    def __init__(self) -> None:
        self._prior_key: tuple[object, ...] | None = None
        self._prior: PriorWeightsCatalog | None = None
        self._transfer_key: tuple[object, ...] | None = None
        self._transfer: ShipTransferCatalogFragment | None = None
        self._combo_space: ShipBuildComboSpace | None = None
        self._combos: tuple[ShipBuildCombo, ...] | None = None

    def prior_weights_catalog(
        self,
        *,
        race_id: int | None,
        buildable_hull_ids: frozenset[int],
        generic_freighter_hull_ids: frozenset[int],
        eligible_engine_ids: frozenset[int],
        eligible_beam_ids: frozenset[int],
        eligible_torp_ids: frozenset[int],
        ship_limit_band: ShipLimitBand,
        base_dir: Path | None,
        build: Callable[[], PriorWeightsCatalog],
    ) -> PriorWeightsCatalog:
        key = (
            race_id,
            buildable_hull_ids,
            generic_freighter_hull_ids,
            eligible_engine_ids,
            eligible_beam_ids,
            eligible_torp_ids,
            ship_limit_band,
            base_dir,
        )
        if key == self._prior_key and self._prior is not None:
            _record_prior(hit=True)
            return self._prior
        catalog = build()
        self._prior_key = key
        self._prior = catalog
        _record_prior(hit=False)
        return catalog

    def ship_transfer_fragment(
        self,
        *,
        prior_fleet_records: tuple[FleetShipRecord, ...],
        observation_key: tuple[object, ...],
        build: Callable[[], ShipTransferCatalogFragment],
    ) -> ShipTransferCatalogFragment:
        """Return the fragment for this row's fleet records and observation.

        Peer scoreboard rows come from the ladder's turn. The store is not
        shared across turns.
        """
        key = (prior_fleet_records, observation_key)
        if key == self._transfer_key and self._transfer is not None:
            _record_transfer(hit=True)
            return self._transfer
        fragment = build()
        self._transfer_key = key
        self._transfer = fragment
        _record_transfer(hit=False)
        return fragment

    def ship_build_combos(
        self,
        space: ShipBuildComboSpace,
        generate: Callable[[tuple[ShipBuildCombo, ...] | None], tuple[ShipBuildCombo, ...]],
    ) -> tuple[ShipBuildCombo, ...]:
        """Return combos for ``space``, reusing objects from the previous rung.

        ``generate(None)`` builds from scratch. ``generate(previous)`` may
        return the previous objects when their weight and bounds still match.
        """
        previous_space = self._combo_space
        previous_combos = self._combos
        if previous_space == space and previous_combos is not None:
            _record_combos(kind="exact", reused=len(previous_combos), allocated=0)
            return previous_combos
        retained = (
            previous_combos
            if previous_space is not None
            and previous_combos is not None
            and space.covers(previous_space)
            else None
        )
        combos = generate(retained)
        reused, allocated = _combo_object_reuse(retained, combos)
        if retained is not None:
            kind = "extend"
        elif previous_space is not None:
            kind = "rebuild"
        else:
            kind = "initial"
        _record_combos(kind=kind, reused=reused, allocated=allocated)
        self._combo_space = space
        self._combos = combos
        return combos
