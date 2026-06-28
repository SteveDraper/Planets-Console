"""Per-row inference NDJSON stream session state."""

from __future__ import annotations

import queue
import uuid
from dataclasses import dataclass, field

from api.analytics.military_score_inference.fleet_torp_overlay import FleetTorpOverlay
from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.inference_cancel import InferenceCancelToken
from api.analytics.military_score_inference.inference_stream_domain_events import (
    InferenceStreamDomainEvent,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.models import InferenceObservation
from api.models.game import TurnInfo


@dataclass
class InferenceRowStreamSession:
    """Per-row NDJSON stream state shared between the request thread and workers."""

    player_id: int
    observation: InferenceObservation
    turn: TurnInfo
    game_id: int
    perspective: int
    turn_number: int
    resolved_mask: ResolvedHullCatalogMask | None = None
    fleet_torp_overlay: FleetTorpOverlay | None = None
    cancel_token: InferenceCancelToken = field(default_factory=InferenceCancelToken)
    event_queue: queue.Queue[InferenceStreamDomainEvent] = field(default_factory=queue.Queue)
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def stream_scope(self) -> InferenceStreamScope:
        return InferenceStreamScope(
            game_id=self.game_id,
            perspective=self.perspective,
            turn_number=self.turn_number,
        )
