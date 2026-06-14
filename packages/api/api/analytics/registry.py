"""Registry for Core turn analytics."""

from api.analytics.catalog import dict_aligned_with_turn_analytic_catalog
from api.analytics.compute_context import AnalyticComputeContext
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.registration import TurnAnalyticHandler
from api.analytics.registrations import TURN_ANALYTIC_REGISTRATIONS
from api.errors import ValidationError
from api.models.game import TurnInfo

_HANDLERS_BY_ID: dict[str, TurnAnalyticHandler] = {
    registration.catalog_entry.id: registration.handler
    for registration in TURN_ANALYTIC_REGISTRATIONS
}

TURN_ANALYTICS: dict[str, TurnAnalyticHandler] = dict_aligned_with_turn_analytic_catalog(
    _HANDLERS_BY_ID,
    role="Core handlers",
)


def get_turn_analytic(analytic_id: str, turn: TurnInfo, options: TurnAnalyticsOptions) -> dict:
    try:
        handler = TURN_ANALYTICS[analytic_id]
    except KeyError as err:
        raise ValidationError(f"Unknown analytic_id: {analytic_id!r}") from err
    ctx = AnalyticComputeContext(turn=turn, options=options)
    return handler(ctx)
