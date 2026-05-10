"""Core base-map analytic."""

from api.models.game import TurnInfo
from api.serialization.planet import planet_to_public_json

ANALYTIC_ID = "base-map"


def get_base_map(turn: TurnInfo) -> dict:
    """Return planet nodes for the fixed map base layer."""
    players_by_id = {pl.id: pl for pl in turn.players}

    def owner_name(owner_id: int) -> str | None:
        pl = players_by_id.get(owner_id)
        return pl.username if pl else None

    nodes = []
    for planet in turn.planets:
        pid = f"p{planet.id}"
        nodes.append(
            {
                "id": pid,
                "label": pid,
                "x": planet.x,
                "y": planet.y,
                "planet": planet_to_public_json(planet),
                "ownerName": owner_name(planet.ownerid),
            }
        )
    return {"analyticId": ANALYTIC_ID, "nodes": nodes, "edges": []}
