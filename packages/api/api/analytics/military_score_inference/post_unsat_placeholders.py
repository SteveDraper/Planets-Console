"""Post-unsat placeholders for residual and no-exact-solution inference rows.

Unknown military ship and observation-derived generic freighter live on
``placeholders[]``, not ``solutions[]``. Residual leftover stays on the row.
"""

from __future__ import annotations

from collections.abc import Mapping

from api.analytics.military_score_inference.component_eligibility import (
    buildable_hull_ids_for_player,
)
from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.models import InferenceObservation
from api.analytics.military_score_inference.ship_build_combos import GENERIC_FREIGHTER_COMBO_ID
from api.concepts.hulls import (
    GENERIC_FREIGHTER_SENTINEL_HULL_ID,
    UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID,
)
from api.concepts.ship_build_military import warship_construction_envelope_2x
from api.models.components import Beam, Engine, Hull, Torpedo
from api.models.game import TurnInfo

UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID = "unknown_military_ship"
PLACEHOLDER_BUILD_SLOT_USAGE = 1


def post_unsat_placeholders(
    observation: InferenceObservation,
    *,
    hulls_by_id: dict[int, Hull],
    engines_by_id: dict[int, Engine],
    beams_by_id: dict[int, Beam],
    torpedos_by_id: dict[int, Torpedo],
    buildable_hull_ids: frozenset[int],
) -> list[dict[str, object]]:
    """Return residual placeholders for unexplained positive ship remainders.

    Unknown military ship emits only when warship remainder is positive and the
    race legal-warship construction envelope is non-empty. Generic freighter
    emits for unexplained positive ``freighterchange``. Does not assign row
    leftover onto ships.
    """
    placeholders: list[dict[str, object]] = []
    envelope = warship_construction_envelope_2x(
        hulls_by_id=hulls_by_id,
        engines_by_id=engines_by_id,
        beams_by_id=beams_by_id,
        torpedos_by_id=torpedos_by_id,
        buildable_hull_ids=buildable_hull_ids,
    )
    warship_remainder = observation.warship_delta
    if warship_remainder > 0 and envelope is not None:
        min_2x, max_2x = envelope
        placeholders.append(
            {
                "id": UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID,
                "hullId": UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID,
                "count": warship_remainder,
                "militaryScoreDelta2xMin": min_2x,
                "militaryScoreDelta2xMax": max_2x,
                "buildSlotUsage": PLACEHOLDER_BUILD_SLOT_USAGE,
            }
        )
    freighter_remainder = observation.freighter_delta
    if freighter_remainder > 0:
        placeholders.append(
            {
                "id": GENERIC_FREIGHTER_COMBO_ID,
                "hullId": GENERIC_FREIGHTER_SENTINEL_HULL_ID,
                "count": freighter_remainder,
                "buildSlotUsage": PLACEHOLDER_BUILD_SLOT_USAGE,
            }
        )
    return placeholders


def post_unsat_placeholders_from_turn(
    observation: InferenceObservation,
    turn: TurnInfo,
    *,
    resolved_mask: ResolvedHullCatalogMask | None = None,
) -> list[dict[str, object]]:
    """Build post-unsat placeholders from the turn catalog and race hull list.

    ``resolved_mask`` is the same hull eligibility the policy ladder solved under.
    ``None`` keeps the default race list (``buildable_hull_ids_for_player`` without
    an override).
    """
    return post_unsat_placeholders(
        observation,
        hulls_by_id={hull.id: hull for hull in turn.hulls},
        engines_by_id={engine.id: engine for engine in turn.engines},
        beams_by_id={beam.id: beam for beam in turn.beams},
        torpedos_by_id={torpedo.id: torpedo for torpedo in turn.torpedos},
        buildable_hull_ids=buildable_hull_ids_for_player(
            turn,
            observation.player_id,
            resolved_mask=resolved_mask,
        ),
    )


def explode_placeholder_to_unit_payloads(
    placeholder: Mapping[str, object],
) -> list[dict[str, object]]:
    """Explode persist ``count = N`` to N unit payloads with the per-unit envelope copied.

    Fleet ingest uses this so a single unknown-military-ship row becomes N unit
    inferred acquisition rows. Does not invent a multi-ship fleet row.
    """
    raw_count = placeholder.get("count", 0)
    if isinstance(raw_count, bool) or not isinstance(raw_count, int) or raw_count <= 0:
        return []
    unit = {**placeholder, "count": 1}
    return [dict(unit) for _ in range(raw_count)]
