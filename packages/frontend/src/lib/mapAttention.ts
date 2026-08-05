/**
 * Shared map attention intents: pulse + optional pan, owned by the map tree.
 * External callers (sidebar) and internal callers (wormhole clicks) share one bus.
 */

import { gameMapCellCenterToFlow } from './cartography/cartographyOverlayGeometry'
import {
  flowCenterFromMapNode,
  flowPointNeedsPan,
  type FlowViewportPane,
} from './mapFlowGeometry'

/** Pulse visual lifetime (matches 0.75s × 4 CSS iterations). */
export const MAP_ATTENTION_PULSE_MS = 3000

export type MapAttentionSpec =
  | {
      kind: 'wormhole-cell'
      mapX: number
      mapY: number
      pan: 'always'
    }
  | {
      kind: 'homeworld-planet'
      planetId: number
      pan: 'if-offscreen'
    }

export type MapAttentionRequest = MapAttentionSpec & { token: number }

export type HomeworldAttentionMarker = {
  planetId: number
  x: number
  y: number
}

export function mapAttentionPulseMs(_kind: MapAttentionSpec['kind']): number {
  return MAP_ATTENTION_PULSE_MS
}

/**
 * Resolve flow target + whether to pan for a pending attention request.
 * Returns null when the request cannot be resolved yet (e.g. missing marker).
 */
export function resolveMapAttentionTarget(
  request: MapAttentionRequest,
  options: {
    viewport: FlowViewportPane
    homeworldMarkers: readonly HomeworldAttentionMarker[]
  }
): { flowX: number; flowY: number; needsPan: boolean } | null {
  if (request.kind === 'wormhole-cell') {
    const { cx, cy } = gameMapCellCenterToFlow(request.mapX, request.mapY)
    return {
      flowX: cx,
      flowY: cy,
      needsPan: request.pan === 'always' || flowPointNeedsPan(cx, cy, options.viewport),
    }
  }

  const marker = options.homeworldMarkers.find(
    (entry) => entry.planetId === request.planetId
  )
  if (marker == null) return null
  const { cx, cy } = flowCenterFromMapNode(marker)
  return {
    flowX: cx,
    flowY: cy,
    needsPan:
      request.pan === 'always' || flowPointNeedsPan(cx, cy, options.viewport),
  }
}

export function isHomeworldPlanetAttention(
  request: MapAttentionRequest | null
): request is Extract<MapAttentionRequest, { kind: 'homeworld-planet' }> {
  return request?.kind === 'homeworld-planet'
}

export function isWormholeCellAttention(
  request: MapAttentionRequest | null
): request is Extract<MapAttentionRequest, { kind: 'wormhole-cell' }> {
  return request?.kind === 'wormhole-cell'
}
