/**
 * Wormhole affordance hit-test for the **map interaction surface**.
 *
 * Emits **map-element** hover: endpoint / edge proximity in flow space from the
 * pane pointer -- not pointer-capture on wormhole paint. Chrome anchors at the
 * hit cell center so it stays visually independent of cursor descriptive hosts.
 */

import type { MapEdge } from '../../api/bff'
import { gameMapCellCenterToFlow } from '../../lib/cartography/cartographyOverlayGeometry'
import {
  WORMHOLE_ENDPOINT_DIAMETER_LY,
  WORMHOLE_ENDPOINT_MIN_DIAMETER_PX,
} from '../../lib/cartography/stellarCartographyTheme'
import {
  clientToFlowPosition,
  safeZoomScale,
} from '../../lib/mapFlowGeometry'
import {
  formatWormholeEndpointHoverLines,
  wormholeMapCellKey,
  type WormholeEndpointHoverInfo,
} from '../../lib/wormholeEndpointHover'
import type { MapHoverPlacement } from '../mapHoverContributionTypes'
import type { MapHitContext } from '../mapInteractionContributorTypes'

/** Pane-pixel half-width for wormhole edge line hit (matches BaseEdge interactionWidth). */
export const WORMHOLE_EDGE_HOVER_RADIUS_PX = 12

export type WormholeEdgeHoverData = {
  isBidirectional?: boolean
  sourceGameX?: number
  sourceGameY?: number
  targetGameX?: number
  targetGameY?: number
}

export type WormholeHitResult = {
  id: string
  lines: readonly string[]
  /** Flow-space anchor at the hit cell (endpoint) or near-end cell (edge). */
  placement: Extract<MapHoverPlacement, { mode: 'anchor' }>
  /** Map cell used for on-hover wormhole line reveal. */
  revealMapX: number
  revealMapY: number
}

function anchorPlacementAtCell(
  mapX: number,
  mapY: number
): Extract<MapHoverPlacement, { mode: 'anchor' }> {
  const { cx, cy } = gameMapCellCenterToFlow(mapX, mapY)
  return { mode: 'anchor', flowX: cx, flowY: cy }
}

function endpointHoverRadiusFlow(scale: number): number {
  const minRadiusFlow = WORMHOLE_ENDPOINT_MIN_DIAMETER_PX / 2 / scale
  return Math.max(WORMHOLE_ENDPOINT_DIAMETER_LY / 2, minRadiusFlow)
}

function distancePointToSegment(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number
): number {
  const dx = bx - ax
  const dy = by - ay
  const lenSq = dx * dx + dy * dy
  if (lenSq <= 0) return Math.hypot(px - ax, py - ay)
  let t = ((px - ax) * dx + (py - ay) * dy) / lenSq
  t = Math.max(0, Math.min(1, t))
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy))
}

/** Edge mid-line / near-end label. */
export function wormholeHoverLabel(
  data: WormholeEdgeHoverData | undefined,
  nearSource: boolean
): string | null {
  if (data == null) return null
  const sx = data.sourceGameX
  const sy = data.sourceGameY
  const tx = data.targetGameX
  const ty = data.targetGameY
  if (sx == null || sy == null || tx == null || ty == null) return null
  if (data.isBidirectional === true) {
    if (nearSource) return `goes to (${tx}, ${ty})`
    return `goes to (${sx}, ${sy})`
  }
  if (nearSource) return `goes to (${tx}, ${ty})`
  return `exit - entrance at (${sx}, ${sy})`
}

function hitTestEndpointAtFlow(
  flowX: number,
  flowY: number,
  scale: number,
  hoverByCell: ReadonlyMap<string, WormholeEndpointHoverInfo>
): WormholeHitResult | null {
  const radiusFlow = endpointHoverRadiusFlow(scale)
  let best: {
    mapX: number
    mapY: number
    dist: number
    info: WormholeEndpointHoverInfo
  } | null = null

  for (const [key, info] of hoverByCell) {
    const [xRaw, yRaw] = key.split(',')
    const mapX = Number(xRaw)
    const mapY = Number(yRaw)
    if (!Number.isFinite(mapX) || !Number.isFinite(mapY)) continue
    const { cx, cy } = gameMapCellCenterToFlow(mapX, mapY)
    const dist = Math.hypot(flowX - cx, flowY - cy)
    if (dist > radiusFlow) continue
    if (best == null || dist < best.dist) {
      best = { mapX, mapY, dist, info }
    }
  }
  if (best == null) return null
  return {
    id: `wormhole:endpoint:${wormholeMapCellKey(best.mapX, best.mapY)}`,
    lines: formatWormholeEndpointHoverLines(best.info),
    placement: anchorPlacementAtCell(best.mapX, best.mapY),
    revealMapX: best.mapX,
    revealMapY: best.mapY,
  }
}

function hitTestEdgeAtFlow(
  flowX: number,
  flowY: number,
  scale: number,
  edges: readonly MapEdge[]
): WormholeHitResult | null {
  const radiusFlow = WORMHOLE_EDGE_HOVER_RADIUS_PX / scale
  let best: {
    dist: number
    nearSource: boolean
    edge: MapEdge
    sx: number
    sy: number
    tx: number
    ty: number
  } | null = null

  for (const edge of edges) {
    if (edge.layer !== 'wormholes') continue
    const sx = edge.sourceGameX
    const sy = edge.sourceGameY
    const tx = edge.targetGameX
    const ty = edge.targetGameY
    if (sx == null || sy == null || tx == null || ty == null) continue
    const source = gameMapCellCenterToFlow(sx, sy)
    const target = gameMapCellCenterToFlow(tx, ty)
    const dist = distancePointToSegment(
      flowX,
      flowY,
      source.cx,
      source.cy,
      target.cx,
      target.cy
    )
    if (dist > radiusFlow) continue
    const distSource = Math.hypot(flowX - source.cx, flowY - source.cy)
    const distTarget = Math.hypot(flowX - target.cx, flowY - target.cy)
    const nearSource = distSource <= distTarget
    if (best == null || dist < best.dist) {
      best = { dist, nearSource, edge, sx, sy, tx, ty }
    }
  }
  if (best == null) return null
  const label = wormholeHoverLabel(
    {
      isBidirectional: best.edge.isBidirectional,
      sourceGameX: best.sx,
      sourceGameY: best.sy,
      targetGameX: best.tx,
      targetGameY: best.ty,
    },
    best.nearSource
  )
  if (label == null) return null
  const nearMapX = best.nearSource ? best.sx : best.tx
  const nearMapY = best.nearSource ? best.sy : best.ty
  // Reveal paints the far end so the wormhole line is visible from the hover side.
  const revealMapX = best.nearSource ? best.tx : best.sx
  const revealMapY = best.nearSource ? best.ty : best.sy
  return {
    id: `wormhole:edge:${best.edge.source}:${best.edge.target}:${best.nearSource ? 's' : 't'}`,
    lines: [label],
    placement: anchorPlacementAtCell(nearMapX, nearMapY),
    revealMapX,
    revealMapY,
  }
}

/**
 * Prefer endpoint icons over edge mid-lines when both are under the pointer.
 * ``displayEdges`` should be the currently painted wormhole-capable edge list
 * (after on-hover reveal filtering).
 */
export function hitTestWormholeAtPointer(
  hit: MapHitContext,
  hoverByCell: ReadonlyMap<string, WormholeEndpointHoverInfo>,
  displayEdges: readonly MapEdge[]
): WormholeHitResult | null {
  if (hit.domNode == null || hit.transform == null) return null
  if (hoverByCell.size === 0 && displayEdges.length === 0) return null
  const flow = clientToFlowPosition(
    hit.clientPos.x,
    hit.clientPos.y,
    hit.domNode,
    hit.transform
  )
  if (flow == null) return null
  const scale = safeZoomScale(hit.transform[2])
  const endpoint = hitTestEndpointAtFlow(flow.x, flow.y, scale, hoverByCell)
  if (endpoint != null) return endpoint
  return hitTestEdgeAtFlow(flow.x, flow.y, scale, displayEdges)
}
