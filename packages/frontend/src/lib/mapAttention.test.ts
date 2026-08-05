import { describe, expect, it } from 'vitest'
import { CELL_CENTER_OFFSET } from './mapFlowGeometry'
import {
  isHomeworldPlanetAttention,
  isWormholeCellAttention,
  resolveMapAttentionTarget,
} from './mapAttention'

describe('resolveMapAttentionTarget', () => {
  const markers = [{ planetId: 10, x: 100, y: 200 }] as const
  const viewport = { x: 400, y: 300, zoom: 1, width: 800, height: 600 }

  it('returns null when a homeworld planet has no marker', () => {
    expect(
      resolveMapAttentionTarget(
        { kind: 'homeworld-planet', planetId: 99, pan: 'if-offscreen', token: 1 },
        { homeworldMarkers: markers, viewport }
      )
    ).toBeNull()
  })

  it('reports needsPan false when the homeworld marker is on-screen', () => {
    const resolved = resolveMapAttentionTarget(
      { kind: 'homeworld-planet', planetId: 10, pan: 'if-offscreen', token: 1 },
      { homeworldMarkers: markers, viewport }
    )
    expect(resolved).not.toBeNull()
    expect(resolved!.flowX).toBeCloseTo(100 + CELL_CENTER_OFFSET)
    expect(resolved!.flowY).toBeCloseTo(-(200 + CELL_CENTER_OFFSET))
    expect(resolved!.needsPan).toBe(false)
  })

  it('reports needsPan true when the homeworld marker is off-screen', () => {
    const resolved = resolveMapAttentionTarget(
      { kind: 'homeworld-planet', planetId: 10, pan: 'if-offscreen', token: 1 },
      {
        homeworldMarkers: markers,
        viewport: { ...viewport, x: -10_000, y: -10_000 },
      }
    )
    expect(resolved?.needsPan).toBe(true)
  })

  it('always pans for wormhole-cell attention', () => {
    const resolved = resolveMapAttentionTarget(
      { kind: 'wormhole-cell', mapX: 5, mapY: 7, pan: 'always', token: 1 },
      { homeworldMarkers: [], viewport }
    )
    expect(resolved).not.toBeNull()
    expect(resolved!.needsPan).toBe(true)
  })
})

describe('attention kind guards', () => {
  it('narrows pending request kinds', () => {
    const homeworld = {
      kind: 'homeworld-planet' as const,
      planetId: 1,
      pan: 'if-offscreen' as const,
      token: 1,
    }
    const wormhole = {
      kind: 'wormhole-cell' as const,
      mapX: 0,
      mapY: 0,
      pan: 'always' as const,
      token: 2,
    }
    expect(isHomeworldPlanetAttention(homeworld)).toBe(true)
    expect(isWormholeCellAttention(homeworld)).toBe(false)
    expect(isWormholeCellAttention(wormhole)).toBe(true)
    expect(isHomeworldPlanetAttention(null)).toBe(false)
  })
})
