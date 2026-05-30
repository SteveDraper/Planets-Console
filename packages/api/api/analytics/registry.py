"""Registry for Core turn analytics."""

from collections.abc import Callable

from api.analytics.base_map import ANALYTIC_ID as BASE_MAP_ID
from api.analytics.base_map import get_base_map
from api.analytics.connections import ANALYTIC_ID as CONNECTIONS_ID
from api.analytics.connections import get_connections_map
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores import ANALYTIC_ID as SCORES_ID
from api.analytics.scores import get_scores_table
from api.analytics.stellar_cartography import ANALYTIC_ID as STELLAR_CARTOGRAPHY_ID
from api.analytics.stellar_cartography import get_stellar_cartography_map
from api.errors import ValidationError
from api.models.game import TurnInfo

TurnAnalyticHandler = Callable[[TurnInfo, TurnAnalyticsOptions], dict]


def _base_map_handler(turn: TurnInfo, options: TurnAnalyticsOptions) -> dict:
    return get_base_map(turn)


def _scores_handler(turn: TurnInfo, options: TurnAnalyticsOptions) -> dict:
    return get_scores_table(turn)


TURN_ANALYTICS: dict[str, TurnAnalyticHandler] = {
    BASE_MAP_ID: _base_map_handler,
    SCORES_ID: _scores_handler,
    CONNECTIONS_ID: get_connections_map,
    STELLAR_CARTOGRAPHY_ID: get_stellar_cartography_map,
}


def get_turn_analytic(analytic_id: str, turn: TurnInfo, options: TurnAnalyticsOptions) -> dict:
    try:
        handler = TURN_ANALYTICS[analytic_id]
    except KeyError as err:
        raise ValidationError(f"Unknown analytic_id: {analytic_id!r}") from err
    return handler(turn, options)
