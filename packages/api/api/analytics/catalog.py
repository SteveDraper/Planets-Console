"""Declarative catalog for turn analytics (ids and SPA-facing metadata)."""

from dataclasses import dataclass
from typing import Literal, TypeVar

AnalyticType = Literal["base", "selectable"]


@dataclass(frozen=True)
class TurnAnalyticCatalogEntry:
    """One turn analytic in the shared catalog."""

    id: str
    name: str
    supports_table: bool
    supports_map: bool
    type: AnalyticType


TURN_ANALYTIC_CATALOG: tuple[TurnAnalyticCatalogEntry, ...] = (
    TurnAnalyticCatalogEntry(
        id="base-map",
        name="Map",
        supports_table=False,
        supports_map=True,
        type="base",
    ),
    TurnAnalyticCatalogEntry(
        id="scores",
        name="Scores",
        supports_table=True,
        supports_map=False,
        type="selectable",
    ),
    TurnAnalyticCatalogEntry(
        id="connections",
        name="Connections",
        supports_table=False,
        supports_map=True,
        type="selectable",
    ),
    TurnAnalyticCatalogEntry(
        id="stellar-cartography",
        name="Stellar Cartography",
        supports_table=False,
        supports_map=True,
        type="selectable",
    ),
)

_CATALOG_BY_ID: dict[str, TurnAnalyticCatalogEntry] = {
    entry.id: entry for entry in TURN_ANALYTIC_CATALOG
}

T = TypeVar("T")


def catalog_entry(analytic_id: str) -> TurnAnalyticCatalogEntry:
    """Return catalog metadata for one turn analytic id."""
    try:
        return _CATALOG_BY_ID[analytic_id]
    except KeyError as err:
        raise KeyError(f"Unknown turn analytic catalog id: {analytic_id!r}") from err


def _validate_registry_ids_match_catalog(
    catalog_ids: set[str],
    registered_ids: set[str],
    *,
    role: str,
) -> None:
    if catalog_ids == registered_ids:
        return
    missing = sorted(catalog_ids - registered_ids)
    extra = sorted(registered_ids - catalog_ids)
    raise RuntimeError(
        f"Turn analytic catalog and {role} are out of sync: "
        f"catalog without registration={missing!r}, registration without catalog={extra!r}"
    )


def tuple_aligned_with_turn_analytic_catalog(
    by_id: dict[str, T],
    catalog: tuple[TurnAnalyticCatalogEntry, ...],
    *,
    role: str,
) -> tuple[T, ...]:
    """Return *by_id* values in catalog order after verifying keys match the catalog exactly."""
    catalog_ids = {entry.id for entry in catalog}
    _validate_registry_ids_match_catalog(catalog_ids, set(by_id), role=role)
    return tuple(by_id[entry.id] for entry in catalog)
