"""Turn analytic dispatch via the Core analytics registry."""

from collections.abc import Callable

from api.analytics import TurnAnalyticsOptions, get_turn_analytic
from api.diagnostics import NOOP_DIAGNOSTICS, Diagnostics
from api.errors import NotFoundError
from api.models.game import TurnInfo
from api.services.turn_load_service import TurnLoadService
from api.transport.connections_options import FlareConnectionMode


class TurnAnalyticService:
    """Compute registered turn analytics for a game, perspective, and turn."""

    def __init__(self, turns: TurnLoadService) -> None:
        self._turns = turns

    def _load_scoreboard_turn(
        self,
        game_id: int,
        perspective: int,
    ) -> Callable[[int], TurnInfo | None]:
        def load_scoreboard_turn(stored_turn_number: int) -> TurnInfo | None:
            try:
                return self._turns.get_turn_info(
                    game_id,
                    perspective,
                    stored_turn_number,
                )
            except OSError, ValueError, KeyError, NotFoundError:
                return None

        return load_scoreboard_turn

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
        return get_scores_row_inference(
            turn,
            player_id,
            load_scoreboard_turn=self._load_scoreboard_turn(game_id, perspective),
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
        return iter_scores_row_inference_stream(
            turn,
            player_id,
            game_id=game_id,
            perspective=perspective,
            load_scoreboard_turn=self._load_scoreboard_turn(game_id, perspective),
        )

    def iter_scores_table_inference_stream(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_ids: tuple[int, ...],
    ):
        from api.analytics.scores import iter_scores_table_inference_stream

        turn = self._turns.get_turn_info(game_id, perspective, turn_number)
        return iter_scores_table_inference_stream(
            turn,
            player_ids,
            game_id=game_id,
            perspective=perspective,
            load_scoreboard_turn=self._load_scoreboard_turn(game_id, perspective),
        )

    def stop_scores_row_inference(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
    ) -> dict[str, object]:
        from api.analytics.scores import stop_scores_row_inference

        return stop_scores_row_inference(
            game_id=game_id,
            perspective=perspective,
            turn_number=turn_number,
            player_id=player_id,
        )

    def get_inference_global_pause_status(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> dict[str, object]:
        from api.analytics.military_score_inference.inference_scheduler import (
            get_inference_row_scheduler,
        )
        from api.analytics.military_score_inference.inference_stream_scope import (
            InferenceStreamScope,
        )

        scope = InferenceStreamScope(
            game_id=game_id,
            perspective=perspective,
            turn_number=turn_number,
        )
        return get_inference_row_scheduler().global_pause_status(scope)

    def pause_inference_globally(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> dict[str, object]:
        from api.analytics.military_score_inference.inference_scheduler import (
            get_inference_row_scheduler,
        )
        from api.analytics.military_score_inference.inference_stream_scope import (
            InferenceStreamScope,
        )

        scope = InferenceStreamScope(
            game_id=game_id,
            perspective=perspective,
            turn_number=turn_number,
        )
        return get_inference_row_scheduler().pause_globally(scope)

    def resume_inference_globally(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> dict[str, object]:
        from api.analytics.military_score_inference.inference_scheduler import (
            get_inference_row_scheduler,
        )
        from api.analytics.military_score_inference.inference_stream_scope import (
            InferenceStreamScope,
        )

        scope = InferenceStreamScope(
            game_id=game_id,
            perspective=perspective,
            turn_number=turn_number,
        )
        return get_inference_row_scheduler().resume_globally(scope)
