"""Core base-map analytic."""

from api.concepts.warp_well import WarpWellKind, map_cell_indices_in_warp_well
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
        normal_well_cells = [
            {"x": gx, "y": gy}
            for gx, gy in map_cell_indices_in_warp_well(planet, WarpWellKind.NORMAL)
        ]
        nodes.append(
            {
                "id": pid,
                "label": pid,
                "x": planet.x,
                "y": planet.y,
                "planet": planet_to_public_json(planet),
                "ownerName": owner_name(planet.ownerid),
                "normalWellCells": normal_well_cells,
            }
        )
    return {"analyticId": ANALYTIC_ID, "nodes": nodes, "edges": []}
