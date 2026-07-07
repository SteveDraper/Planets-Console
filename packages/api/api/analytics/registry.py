"""Registry for Core turn analytics."""

from collections.abc import Callable, Mapping

from api.analytics.base_map import REGISTRATION as BASE_MAP_REGISTRATION
from api.analytics.catalog import (
    TURN_ANALYTIC_CATALOG,
    tuple_aligned_with_turn_analytic_catalog,
)
from api.analytics.compute_context import make_analytic_compute_context
from api.analytics.connections import REGISTRATION as CONNECTIONS_REGISTRATION
from api.analytics.fleet.registration import REGISTRATION as FLEET_REGISTRATION
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

_IMPORTED_REGISTRATIONS: tuple[TurnAnalyticRegistration, ...] = (
    BASE_MAP_REGISTRATION,
    SCORES_REGISTRATION,
    CONNECTIONS_REGISTRATION,
    STELLAR_CARTOGRAPHY_REGISTRATION,
    FLEET_REGISTRATION,
)

validate_turn_analytic_registrations(_IMPORTED_REGISTRATIONS)

# The catalog is the single source of truth for analytic identity and order.
# Registrations are aligned to it with the same helper the BFF uses for its
# descriptors, so a missing/extra registration fails at import and the public
# order always follows the catalog.
TURN_ANALYTIC_REGISTRATIONS: tuple[TurnAnalyticRegistration, ...] = (
    tuple_aligned_with_turn_analytic_catalog(
        {registration.catalog_entry.id: registration for registration in _IMPORTED_REGISTRATIONS},
        TURN_ANALYTIC_CATALOG,
        role="Core turn analytic registrations",
    )
)

TURN_ANALYTICS: dict[str, TurnAnalyticHandler] = {
    registration.catalog_entry.id: registration.compute
    for registration in TURN_ANALYTIC_REGISTRATIONS
}


def get_turn_analytic(
    analytic_id: str,
    turn: TurnInfo,
    options: TurnAnalyticsOptions,
    *,
    load_turn: Callable[[int], TurnInfo | None] | None = None,
    export_services: Mapping[str, object] | None = None,
) -> dict:
    try:
        handler = TURN_ANALYTICS[analytic_id]
    except KeyError as err:
        raise ValidationError(f"Unknown analytic_id: {analytic_id!r}") from err
    return handler(
        make_analytic_compute_context(
            turn,
            options,
            load_turn=load_turn,
            export_services=export_services,
        )
    )
