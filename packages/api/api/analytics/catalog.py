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


T = TypeVar("T")


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


def dict_aligned_with_turn_analytic_catalog(by_id: dict[str, T], *, role: str) -> dict[str, T]:
    """Return *by_id* in catalog order after verifying its keys match the catalog exactly."""
    from api.analytics.registrations import TURN_ANALYTIC_REGISTRATIONS

    catalog_ids = {entry.catalog_entry.id for entry in TURN_ANALYTIC_REGISTRATIONS}
    _validate_registry_ids_match_catalog(catalog_ids, set(by_id), role=role)
    return {
        entry.catalog_entry.id: by_id[entry.catalog_entry.id]
        for entry in TURN_ANALYTIC_REGISTRATIONS
    }


def tuple_aligned_with_turn_analytic_catalog(by_id: dict[str, T], *, role: str) -> tuple[T, ...]:
    """Return *by_id* values in catalog order after verifying keys match the catalog exactly."""
    from api.analytics.registrations import TURN_ANALYTIC_REGISTRATIONS

    catalog_ids = {entry.catalog_entry.id for entry in TURN_ANALYTIC_REGISTRATIONS}
    _validate_registry_ids_match_catalog(catalog_ids, set(by_id), role=role)
    return tuple(by_id[entry.catalog_entry.id] for entry in TURN_ANALYTIC_REGISTRATIONS)


def catalog_entry(analytic_id: str) -> TurnAnalyticCatalogEntry:
    try:
        return _CATALOG_BY_ID[analytic_id]
    except KeyError as err:
        raise KeyError(f"Unknown turn analytic catalog id: {analytic_id!r}") from err


from api.analytics.registrations import TURN_ANALYTIC_REGISTRATIONS  # noqa: E402

TURN_ANALYTIC_CATALOG: tuple[TurnAnalyticCatalogEntry, ...] = tuple(
    registration.catalog_entry for registration in TURN_ANALYTIC_REGISTRATIONS
)

_CATALOG_BY_ID: dict[str, TurnAnalyticCatalogEntry] = {
    entry.id: entry for entry in TURN_ANALYTIC_CATALOG
}
