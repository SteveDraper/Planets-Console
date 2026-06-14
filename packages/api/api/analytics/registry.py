"""Registry for Core turn analytics."""

from api.analytics.base_map import REGISTRATION as BASE_MAP_REGISTRATION
from api.analytics.catalog import TurnAnalyticCatalogEntry, publish_turn_analytic_catalog
from api.analytics.compute_context import make_analytic_compute_context
from api.analytics.connections import REGISTRATION as CONNECTIONS_REGISTRATION
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.registration import (
    TurnAnalyticHandler,
    TurnAnalyticRegistration,
    validate_turn_analytic_registrations,
)
from api.analytics.scores import REGISTRATION as SCORES_REGISTRATION
from api.analytics.stellar_cartography import REGISTRATION as STELLAR_CARTOGRAPHY_REGISTRATION
from api.errors import ValidationError
from api.models.game import TurnInfo

TURN_ANALYTIC_REGISTRATIONS: tuple[TurnAnalyticRegistration, ...] = (
    BASE_MAP_REGISTRATION,
    SCORES_REGISTRATION,
    CONNECTIONS_REGISTRATION,
    STELLAR_CARTOGRAPHY_REGISTRATION,
)

validate_turn_analytic_registrations(TURN_ANALYTIC_REGISTRATIONS)

_DERIVED_TURN_ANALYTIC_CATALOG: tuple[TurnAnalyticCatalogEntry, ...] = tuple(
    registration.catalog_entry for registration in TURN_ANALYTIC_REGISTRATIONS
)
publish_turn_analytic_catalog(_DERIVED_TURN_ANALYTIC_CATALOG)

TURN_ANALYTIC_CATALOG: tuple[TurnAnalyticCatalogEntry, ...] = _DERIVED_TURN_ANALYTIC_CATALOG

TURN_ANALYTICS: dict[str, TurnAnalyticHandler] = {
    registration.catalog_entry.id: registration.compute
    for registration in TURN_ANALYTIC_REGISTRATIONS
}


def get_turn_analytic(analytic_id: str, turn: TurnInfo, options: TurnAnalyticsOptions) -> dict:
    try:
        handler = TURN_ANALYTICS[analytic_id]
    except KeyError as err:
        raise ValidationError(f"Unknown analytic_id: {analytic_id!r}") from err
    return handler(make_analytic_compute_context(turn, options))
