/**
 * Panel candidate click → selection + map flash; conditional pan resolved on the map.
 */

import { flowCenterFromMapNode, flowPointNeedsPan } from '../../components/map-graph/geometry'
import { useHomeworldCandidateFlashStore } from '../../stores/homeworldCandidateFlash'
import { useHomeworldLocatorSelectionStore } from '../../stores/homeworldLocatorSelection'

export type HomeworldCandidateAttentionMarker = {
  planetId: number
  x: number
  y: number
}

/**
 * Select a candidate planet for assert-focus and request a map marker flash.
 * Pan is decided later inside the React Flow tree (viewport-aware).
 */
export function selectHomeworldCandidateForMapAttention(planetId: number): void {
  useHomeworldLocatorSelectionStore.getState().setSelection({ kind: 'planet', planetId })
  useHomeworldCandidateFlashStore.getState().flashPlanet(planetId)
}

/**
 * Resolve whether a flashing candidate needs a viewport pan (zoom unchanged).
 * Returns null when the planet has no map marker.
 */
export function resolveHomeworldCandidatePan(
  planetId: number,
  markers: readonly HomeworldCandidateAttentionMarker[],
  viewport: { x: number; y: number; zoom: number; width: number; height: number }
): { flowX: number; flowY: number; needsPan: boolean } | null {
  const marker = markers.find((entry) => entry.planetId === planetId)
  if (marker == null) return null
  const { cx, cy } = flowCenterFromMapNode(marker)
  return {
    flowX: cx,
    flowY: cy,
    needsPan: flowPointNeedsPan(cx, cy, viewport),
  }
}
