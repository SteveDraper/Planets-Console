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


TURN_ANALYTIC_CATALOG: tuple[TurnAnalyticCatalogEntry, ...] = ()
_CATALOG_BY_ID: dict[str, TurnAnalyticCatalogEntry] = {}

T = TypeVar("T")


def publish_turn_analytic_catalog(catalog: tuple[TurnAnalyticCatalogEntry, ...]) -> None:
    """Install the derived catalog published by ``api.analytics.registry`` at import."""
    global TURN_ANALYTIC_CATALOG
    if _CATALOG_BY_ID:
        raise RuntimeError("Turn analytic catalog already published")
    TURN_ANALYTIC_CATALOG = catalog
    _CATALOG_BY_ID.update((entry.id, entry) for entry in catalog)


def _ensure_turn_analytic_catalog_published() -> None:
    if _CATALOG_BY_ID:
        return
    import api.analytics.registry  # noqa: F401


def catalog_entry(analytic_id: str) -> TurnAnalyticCatalogEntry:
    """Return catalog metadata for one turn analytic id."""
    _ensure_turn_analytic_catalog_published()
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


def dict_aligned_with_turn_analytic_catalog(
    by_id: dict[str, T],
    catalog: tuple[TurnAnalyticCatalogEntry, ...],
    *,
    role: str,
) -> dict[str, T]:
    """Return *by_id* in catalog order after verifying its keys match the catalog exactly."""
    catalog_ids = {entry.id for entry in catalog}
    _validate_registry_ids_match_catalog(catalog_ids, set(by_id), role=role)
    return {entry.id: by_id[entry.id] for entry in catalog}


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
