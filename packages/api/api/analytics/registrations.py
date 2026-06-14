"""Aggregated Core turn analytic registrations."""

from api.analytics.base_map import REGISTRATION as BASE_MAP_REGISTRATION
from api.analytics.catalog import TurnAnalyticCatalogEntry
from api.analytics.connections import REGISTRATION as CONNECTIONS_REGISTRATION
from api.analytics.registration import (
    TurnAnalyticRegistration,
    validate_turn_analytic_registrations,
)
from api.analytics.scores import REGISTRATION as SCORES_REGISTRATION
from api.analytics.stellar_cartography import REGISTRATION as STELLAR_CARTOGRAPHY_REGISTRATION

TURN_ANALYTIC_REGISTRATIONS: tuple[TurnAnalyticRegistration, ...] = (
    BASE_MAP_REGISTRATION,
    SCORES_REGISTRATION,
    CONNECTIONS_REGISTRATION,
    STELLAR_CARTOGRAPHY_REGISTRATION,
)

validate_turn_analytic_registrations(TURN_ANALYTIC_REGISTRATIONS)

TURN_ANALYTIC_CATALOG: tuple[TurnAnalyticCatalogEntry, ...] = tuple(
    registration.catalog_entry for registration in TURN_ANALYTIC_REGISTRATIONS
)
