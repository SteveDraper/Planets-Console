"""Turn analytic dispatch via the Core analytics registry."""

from api.analytics import TurnAnalyticsOptions, get_turn_analytic
from api.diagnostics import NOOP_DIAGNOSTICS, Diagnostics
from api.errors import NotFoundError
from api.services.turn_load_service import TurnLoadService
from api.transport.connections_options import FlareConnectionMode


class TurnAnalyticService:
    """Compute registered turn analytics for a game, perspective, and turn."""

    def __init__(self, turns: TurnLoadService) -> None:
        self._turns = turns

    def get_turn_analytics(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        analytic_id: str,
        *,
        connection_warp_speed: int | None = None,
        connection_gravitonic_movement: bool = False,
        connection_flare_mode: FlareConnectionMode | str = FlareConnectionMode.OFF,
        connection_flare_depth: int = 1,
        connection_include_illustrative_routes: bool = False,
        diagnostics: Diagnostics = NOOP_DIAGNOSTICS,
    ) -> dict:
        turn = self._turns.get_turn_info(game_id, perspective, turn_number)
        return get_turn_analytic(
            analytic_id,
            turn,
            TurnAnalyticsOptions(
                connection_warp_speed=connection_warp_speed,
                connection_gravitonic_movement=connection_gravitonic_movement,
                connection_flare_mode=connection_flare_mode,
                connection_flare_depth=connection_flare_depth,
                connection_include_illustrative_routes=connection_include_illustrative_routes,
                diagnostics=diagnostics,
            ),
        )

    def get_scores_row_inference(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> dict[str, object]:
        from api.analytics.scores import get_scores_row_inference

        turn = self._turns.get_turn_info(game_id, perspective, turn_number)

        def load_scoreboard_turn(stored_turn_number: int):
            try:
                return self._turns.get_turn_info(
                    game_id,
                    perspective,
                    stored_turn_number,
                )
            except OSError, ValueError, KeyError, NotFoundError:
                return None

        return get_scores_row_inference(
            turn,
            player_id,
            load_scoreboard_turn=load_scoreboard_turn,
        )

    def iter_scores_row_inference_stream(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ):
        from api.analytics.scores import iter_scores_row_inference_stream

        turn = self._turns.get_turn_info(game_id, perspective, turn_number)

        def load_scoreboard_turn(stored_turn_number: int):
            try:
                return self._turns.get_turn_info(
                    game_id,
                    perspective,
                    stored_turn_number,
                )
            except OSError, ValueError, KeyError, NotFoundError:
                return None

        return iter_scores_row_inference_stream(
            turn,
            player_id,
            load_scoreboard_turn=load_scoreboard_turn,
        )
