/**
 * Region overlay descriptive hit-test for the **map interaction surface**.
 */

import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { formatRegionOverlayHoverLine } from '../../components/map-graph/formatRegionOverlayHover'
import { clientToFlowPosition } from '../../lib/mapFlowGeometry'
import { collectRegionOverlayHoverSummaries } from '../../lib/mapRegionOverlayHitTest'
import { flowCenterToPlanet } from '../../lib/planetSpatialGrid'
import type { MapHitContext } from '../mapInteractionContributorTypes'

/** Hit-test filtered overlays under a client pointer in continuous map coords. */
export function regionOverlayHoverLinesAtClient(
  regionOverlays: readonly MapRegionOverlay[],
  clientX: number,
  clientY: number,
  domNode: HTMLElement | null,
  transform: [number, number, number] | undefined
): string[] {
  const flow = clientToFlowPosition(clientX, clientY, domNode, transform)
  if (flow == null) return []
  const { px, py } = flowCenterToPlanet(flow.x, flow.y)
  return collectRegionOverlayHoverSummaries(
    regionOverlays,
    px,
    py,
    formatRegionOverlayHoverLine
  )
}

export function hitTestRegionLinesAtPointer(
  hit: MapHitContext,
  regionOverlays: readonly MapRegionOverlay[]
): string[] {
  if (regionOverlays.length === 0) return []
  return regionOverlayHoverLinesAtClient(
    regionOverlays,
    hit.clientPos.x,
    hit.clientPos.y,
    hit.domNode,
    hit.transform
  )
}
