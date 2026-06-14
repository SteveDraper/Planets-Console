"""Core Stellar Cartography map analytic."""

from api.analytics.catalog import TurnAnalyticCatalogEntry
from api.analytics.compute_context import AnalyticComputeContext
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.registration import TurnAnalyticRegistration
from api.concepts.stellar_cartography.black_holes import ergosphere_outer_radius
from api.concepts.stellar_cartography.layers import (
    LAYER_BLACK_HOLES,
    LAYER_DEBRIS_DISKS,
    LAYER_ION_STORMS,
    LAYER_NEBULAE,
    LAYER_WORMHOLES,
)
from api.concepts.stellar_cartography.star_clusters import (
    neutron_cluster_names,
    star_cluster_layer,
    stars_grouped_by_name,
)
from api.models.game import TurnInfo
from api.models.space import IonStorm, Wormhole

ANALYTIC_ID = "stellar-cartography"


def ion_storm_class(voltage: int) -> int:
    """Map ion storm voltage to wiki hazard class 1..5."""
    if voltage >= 200:
        return 5
    if voltage >= 150:
        return 4
    if voltage >= 100:
        return 3
    if voltage >= 50:
        return 2
    return 1


def _ion_storm_overlay(storm: IonStorm) -> dict:
    return {
        "layer": LAYER_ION_STORMS,
        "id": f"is-{storm.id}",
        "x": storm.x,
        "y": storm.y,
        "radius": storm.radius,
        "voltage": storm.voltage,
        "class": ion_storm_class(storm.voltage),
        "heading": storm.heading,
        "warp": storm.warp,
        "parentId": storm.parentid,
        "isGrowing": storm.isgrowing,
    }


def _wormhole_has_known_target(wormhole: Wormhole) -> bool:
    return not (wormhole.targetx == 0 and wormhole.targety == 0)


def _find_reverse_wormhole(
    wormhole: Wormhole, by_entrance: dict[tuple[int, int, int, int], Wormhole]
) -> Wormhole | None:
    return by_entrance.get((wormhole.targetx, wormhole.targety, wormhole.x, wormhole.y))


def _wormhole_nodes_and_edges(wormholes: list[Wormhole]) -> tuple[list[dict], list[dict]]:
    nodes: list[dict] = []
    edges: list[dict] = []
    seen_pairs: set[tuple[int, int]] = set()

    by_entrance = {(wh.x, wh.y, wh.targetx, wh.targety): wh for wh in wormholes}

    for wormhole in wormholes:
        nodes.append(
            {
                "id": f"wh-{wormhole.id}",
                "x": wormhole.x,
                "y": wormhole.y,
                "layer": LAYER_WORMHOLES,
            }
        )

        if not _wormhole_has_known_target(wormhole):
            continue

        partner = _find_reverse_wormhole(wormhole, by_entrance)
        if partner is not None:
            pair_key = tuple(sorted((wormhole.id, partner.id)))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            edges.append(
                {
                    "source": f"wh-{wormhole.id}",
                    "target": f"wh-{partner.id}",
                    "layer": LAYER_WORMHOLES,
                    "isBidirectional": True,
                    "stability": wormhole.stability,
                    "name": wormhole.name,
                    "partnerId": partner.id,
                }
            )
            continue

        exit_node_id = f"wh-exit-{wormhole.id}"
        nodes.append(
            {
                "id": exit_node_id,
                "x": wormhole.targetx,
                "y": wormhole.targety,
                "layer": LAYER_WORMHOLES,
            }
        )
        edges.append(
            {
                "source": f"wh-{wormhole.id}",
                "target": exit_node_id,
                "layer": LAYER_WORMHOLES,
                "isBidirectional": False,
                "stability": wormhole.stability,
                "name": wormhole.name,
            }
        )

    return nodes, edges


def _debris_disk_overlay(planet) -> dict | None:
    """Disk seed planets carry border radius in ``debrisdisk`` (values > 1)."""
    if planet.debrisdisk <= 1:
        return None
    return {
        "layer": LAYER_DEBRIS_DISKS,
        "id": f"dd-{planet.id}",
        "x": planet.x,
        "y": planet.y,
        "radius": planet.debrisdisk,
        "name": planet.name,
        "planetId": planet.id,
    }


def compute_stellar_cartography_map(ctx: AnalyticComputeContext) -> dict:
    """Return cartography overlay circles and wormhole graph geometry for the turn."""
    turn = ctx.turn
    overlay_circles: list[dict] = []

    for planet in turn.planets:
        debris_disk = _debris_disk_overlay(planet)
        if debris_disk is not None:
            overlay_circles.append(debris_disk)

    for nebula in turn.nebulas:
        overlay_circles.append(
            {
                "layer": LAYER_NEBULAE,
                "id": f"neb-{nebula.id}",
                "x": nebula.x,
                "y": nebula.y,
                "radius": nebula.radius,
                "name": nebula.name,
                "intensity": nebula.intensity,
                "gas": nebula.gas,
            }
        )

    for storm in turn.ionstorms:
        overlay_circles.append(_ion_storm_overlay(storm))

    clusters_by_name = stars_grouped_by_name(turn.stars)
    neutron_names = neutron_cluster_names(turn.stars)
    for star in turn.stars:
        overlay_circles.append(
            {
                "layer": star_cluster_layer(star.name, neutron_names),
                "id": f"star-{star.id}",
                "x": star.x,
                "y": star.y,
                "radius": star.radius,
                "name": star.name,
                "temp": star.temp,
                "mass": star.mass,
                "planets": star.planets,
            }
        )

    for blackhole in turn.blackholes:
        overlay_circles.append(
            {
                "layer": LAYER_BLACK_HOLES,
                "id": f"bh-{blackhole.id}",
                "x": blackhole.x,
                "y": blackhole.y,
                "radius": ergosphere_outer_radius(blackhole.coreradius, blackhole.bandradius),
                "name": blackhole.name,
                "coreRadius": blackhole.coreradius,
                "bandRadius": blackhole.bandradius,
            }
        )

    wormhole_nodes, wormhole_edges = _wormhole_nodes_and_edges(turn.wormholes)

    meta = {
        "debrisDisks": sum(1 for planet in turn.planets if planet.debrisdisk > 1),
        "nebulae": len(turn.nebulas),
        "ionStorms": len(turn.ionstorms),
        "nuIonStorms": turn.settings.nuionstorms,
        "starClusters": len(clusters_by_name) - len(neutron_names),
        "neutronClusters": len(neutron_names),
        "blackHoles": len(turn.blackholes),
        "wormholes": len(turn.wormholes),
        "wormholeEdges": len(wormhole_edges),
    }

    return {
        "analyticId": ANALYTIC_ID,
        "overlayCircles": overlay_circles,
        "nodes": wormhole_nodes,
        "edges": wormhole_edges,
        "meta": meta,
    }


def get_stellar_cartography_map(
    turn: TurnInfo,
    options: TurnAnalyticsOptions | None = None,
) -> dict:
    """Convenience entry for tests and direct callers."""
    return compute_stellar_cartography_map(
        AnalyticComputeContext(turn=turn, options=options or TurnAnalyticsOptions())
    )


REGISTRATION = TurnAnalyticRegistration(
    catalog_entry=TurnAnalyticCatalogEntry(
        id=ANALYTIC_ID,
        name="Stellar Cartography",
        supports_table=False,
        supports_map=True,
        type="selectable",
    ),
    compute=compute_stellar_cartography_map,
)
