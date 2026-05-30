import type { MapEdge } from '../../api/bff'
import { wormholeMapCellKey } from '../../lib/wormholeEndpointHover'

export type WormholeDisplayMode = 'off' | 'always' | 'on-hover'

export const WORMHOLE_DISPLAY_MODE_LABELS: Record<WormholeDisplayMode, string> = {
  off: 'Off',
  'on-hover': 'On hover',
  always: 'Always',
}

export const WORMHOLE_DISPLAY_MODES: readonly WormholeDisplayMode[] = [
  'off',
  'on-hover',
  'always',
] as const

export function defaultWormholeDisplayMode(): WormholeDisplayMode {
  return 'always'
}

export function isWormholeCartographyActive(mode: WormholeDisplayMode): boolean {
  return mode !== 'off'
}

export function areWormholeLinesAlwaysVisible(mode: WormholeDisplayMode): boolean {
  return mode === 'always'
}

export function isWormholeEdgeRevealed(
  edge: MapEdge,
  revealCellKey: string | null
): boolean {
  if (revealCellKey == null) return false
  const sx = edge.sourceGameX
  const sy = edge.sourceGameY
  const tx = edge.targetGameX
  const ty = edge.targetGameY
  if (sx == null || sy == null || tx == null || ty == null) return false
  return (
    wormholeMapCellKey(sx, sy) === revealCellKey ||
    wormholeMapCellKey(tx, ty) === revealCellKey
  )
}

/** Apply on-hover line visibility; other modes leave edges unchanged. */
export function filterWormholeEdgesForDisplayMode(
  edges: readonly MapEdge[],
  mode: WormholeDisplayMode,
  revealCellKey: string | null
): MapEdge[] {
  if (mode === 'off') {
    return edges.filter((edge) => edge.layer !== 'wormholes')
  }
  if (mode === 'always') {
    return [...edges]
  }
  return edges.filter((edge) => {
    if (edge.layer !== 'wormholes') return true
    return isWormholeEdgeRevealed(edge, revealCellKey)
  })
}

export function migratePersistedWormholeLayer(
  layers: Record<string, unknown> | undefined,
  wormholeDisplayMode: WormholeDisplayMode | undefined
): { layers: Record<string, unknown>; wormholeDisplayMode: WormholeDisplayMode } {
  const nextLayers = { ...(layers ?? {}) }
  let mode = wormholeDisplayMode
  if ('wormholes' in nextLayers) {
    const legacy = nextLayers.wormholes
    if (mode == null) {
      mode = legacy === false ? 'off' : 'always'
    }
    delete nextLayers.wormholes
  }
  return {
    layers: nextLayers,
    wormholeDisplayMode: mode ?? defaultWormholeDisplayMode(),
  }
}
