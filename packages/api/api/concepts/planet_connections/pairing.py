"""Pair keys for undirected planet pair sets."""

from __future__ import annotations

from api.models.planet import Planet


def _canonical_pair_id(planet_a: Planet, planet_b: Planet) -> tuple[int, int]:
    """Lower planet id first for set keys (matches route ``from < to``)."""
    ia, ib = planet_a.id, planet_b.id
    if ia < ib:
        return (ia, ib)
    return (ib, ia)
