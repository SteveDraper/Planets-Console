import type { MapEdge, WormholeUnknownEntrance } from '../api/bff'

export type WormholeEndpointDirection = 'entry only' | 'exit only'

export type WormholeEndpointHoverInfo =
  | {
      kind: 'known'
      stability?: number
      otherEndX: number
      otherEndY: number
      direction?: WormholeEndpointDirection
    }
  | { kind: 'unexplored' }

export function wormholeMapCellKey(x: number, y: number): string {
  return `${x},${y}`
}

function assignKnownEndpointHover(
  index: Map<string, WormholeEndpointHoverInfo>,
  x: number,
  y: number,
  info: Extract<WormholeEndpointHoverInfo, { kind: 'known' }>
): void {
  index.set(wormholeMapCellKey(x, y), info)
}

/** Index wormhole endpoint hover metadata by map cell (x, y). */
export function buildWormholeEndpointHoverIndex(
  edges: readonly MapEdge[],
  unknownEntrances: readonly WormholeUnknownEntrance[] = []
): Map<string, WormholeEndpointHoverInfo> {
  const index = new Map<string, WormholeEndpointHoverInfo>()

  for (const edge of edges) {
    if (edge.layer !== 'wormholes') continue
    const sx = edge.sourceGameX
    const sy = edge.sourceGameY
    const tx = edge.targetGameX
    const ty = edge.targetGameY
    if (sx == null || sy == null || tx == null || ty == null) continue

    const stability = edge.stability
    const base = stability != null ? { stability } : {}

    if (edge.isBidirectional === true) {
      assignKnownEndpointHover(index, sx, sy, {
        kind: 'known',
        ...base,
        otherEndX: tx,
        otherEndY: ty,
      })
      assignKnownEndpointHover(index, tx, ty, {
        kind: 'known',
        ...base,
        otherEndX: sx,
        otherEndY: sy,
      })
      continue
    }

    assignKnownEndpointHover(index, sx, sy, {
      kind: 'known',
      ...base,
      otherEndX: tx,
      otherEndY: ty,
      direction: 'entry only',
    })
    assignKnownEndpointHover(index, tx, ty, {
      kind: 'known',
      ...base,
      otherEndX: sx,
      otherEndY: sy,
      direction: 'exit only',
    })
  }

  for (const entrance of unknownEntrances) {
    index.set(wormholeMapCellKey(entrance.x, entrance.y), { kind: 'unexplored' })
  }

  return index
}

export function formatWormholeEndpointHoverLines(
  info: WormholeEndpointHoverInfo
): string[] {
  if (info.kind === 'unexplored') {
    return ['unexplored']
  }
  const lines: string[] = []
  if (info.stability != null) {
    lines.push(`stability: ${info.stability}`)
  }
  const linked = `(${info.otherEndX}, ${info.otherEndY})`
  const preposition = info.direction === 'exit only' ? 'from' : 'to'
  lines.push(`wormhole ${preposition} ${linked}`)
  if (info.direction != null) {
    lines.push(info.direction)
  }
  return lines
}

/** Map cell to recenter on when a known wormhole endpoint icon is clicked; null if unknown target. */
export function wormholeEndpointRecenterGameCoords(
  info: WormholeEndpointHoverInfo
): { x: number; y: number } | null {
  if (info.kind !== 'known') return null
  return { x: info.otherEndX, y: info.otherEndY }
}
