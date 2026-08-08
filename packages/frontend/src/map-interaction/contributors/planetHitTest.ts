/**
 * Planet descriptive hit-test helpers for the **map interaction surface**.
 */

import type { CombinedMapData } from '../../api/bff'
import {
  findClosestPlanetWithinRadius,
  flowCenterToPlanet,
  type PlanetSpatialGrid,
} from '../../lib/planetSpatialGrid'
import { clientToFlowPosition, flowCenterFromMapNode, safeZoomScale } from '../../lib/mapFlowGeometry'
import type { MapHitContext } from '../mapInteractionContributorTypes'
import type { MapNodeLabelSource } from '../../components/map-graph/FixedSizeDotsOverlay'

/** Mouse distance from dot center (px) at which the planet label is shown. */
export const PLANET_LABEL_HOVER_RADIUS_PX = 14

export type PlanetHitResult = {
  nodeId: string
  mapX: number
  mapY: number
  flowX: number
  flowY: number
  labelSource: MapNodeLabelSource | undefined
}

export function hitTestPlanetAtPointer(
  hit: MapHitContext,
  planetGrid: PlanetSpatialGrid | null,
  mapNodes: CombinedMapData['nodes'],
  labelSourceByNodeId: Map<string, MapNodeLabelSource>
): PlanetHitResult | null {
  if (planetGrid == null || hit.domNode == null || hit.transform == null) return null
  const flow = clientToFlowPosition(
    hit.clientPos.x,
    hit.clientPos.y,
    hit.domNode,
    hit.transform
  )
  if (flow == null) return null
  const scale = safeZoomScale(hit.transform[2])
  const radiusFlow = PLANET_LABEL_HOVER_RADIUS_PX / scale
  const { px, py } = flowCenterToPlanet(flow.x, flow.y)
  const closestId = findClosestPlanetWithinRadius(planetGrid, px, py, radiusFlow)
  if (closestId == null) return null
  const mapNode = mapNodes.find((n) => n.id === closestId)
  if (mapNode == null) return null
  const labelSource = labelSourceByNodeId.get(closestId)
  const { cx, cy } = flowCenterFromMapNode(mapNode)
  const mapX =
    labelSource != null && Number.isFinite(labelSource.mapX)
      ? labelSource.mapX
      : Number(mapNode.x)
  const mapY =
    labelSource != null && Number.isFinite(labelSource.mapY)
      ? labelSource.mapY
      : Number(mapNode.y)
  return {
    nodeId: closestId,
    mapX,
    mapY,
    flowX: cx,
    flowY: cy,
    labelSource,
  }
}

export function hitTestWaypointAtPointer(
  hit: MapHitContext,
  waypointGrid: PlanetSpatialGrid | null
): string | null {
  if (waypointGrid == null || hit.domNode == null || hit.transform == null) return null
  const flow = clientToFlowPosition(
    hit.clientPos.x,
    hit.clientPos.y,
    hit.domNode,
    hit.transform
  )
  if (flow == null) return null
  const scale = safeZoomScale(hit.transform[2])
  const radiusFlow = PLANET_LABEL_HOVER_RADIUS_PX / scale
  const { px, py } = flowCenterToPlanet(flow.x, flow.y)
  return findClosestPlanetWithinRadius(waypointGrid, px, py, radiusFlow)
}

export function resolvePinnedPlanet(
  pinnedNodeId: string,
  mapNodes: CombinedMapData['nodes'],
  labelSourceByNodeId: Map<string, MapNodeLabelSource>
): PlanetHitResult | null {
  const mapNode = mapNodes.find((n) => n.id === pinnedNodeId)
  if (mapNode == null) return null
  const labelSource = labelSourceByNodeId.get(pinnedNodeId)
  const { cx, cy } = flowCenterFromMapNode(mapNode)
  return {
    nodeId: pinnedNodeId,
    mapX:
      labelSource != null && Number.isFinite(labelSource.mapX)
        ? labelSource.mapX
        : Number(mapNode.x),
    mapY:
      labelSource != null && Number.isFinite(labelSource.mapY)
        ? labelSource.mapY
        : Number(mapNode.y),
    flowX: cx,
    flowY: cy,
    labelSource,
  }
}
