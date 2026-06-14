"""Registry for Core turn analytics."""

from api.analytics.compute_context import AnalyticComputeContext
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.registration import TurnAnalyticHandler, TurnAnalyticRegistration
from api.analytics.registrations import TURN_ANALYTIC_REGISTRATIONS
from api.errors import ValidationError
from api.models.game import TurnInfo

_TURN_ANALYTIC_REGISTRATIONS_BY_ID: dict[str, TurnAnalyticRegistration] = {
    registration.catalog_entry.id: registration for registration in TURN_ANALYTIC_REGISTRATIONS
}


TURN_ANALYTICS: dict[str, TurnAnalyticHandler] = {
    analytic_id: registration.compute
    for analytic_id, registration in _TURN_ANALYTIC_REGISTRATIONS_BY_ID.items()
}


def get_turn_analytic(analytic_id: str, turn: TurnInfo, options: TurnAnalyticsOptions) -> dict:
    try:
        handler = TURN_ANALYTICS[analytic_id]
    except KeyError as err:
        raise ValidationError(f"Unknown analytic_id: {analytic_id!r}") from err
    ctx = AnalyticComputeContext(turn=turn, options=options, diagnostics=options.diagnostics)
    return handler(ctx)
