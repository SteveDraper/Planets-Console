import { describe, expect, it } from 'vitest'
import {
  buildPlanetSpatialGrid,
  findClosestPlanetWithinRadius,
  flowCenterToPlanet,
  PLANET_CELL_CENTER_OFFSET,
} from './planetSpatialGrid'

describe('flowCenterToPlanet', () => {
  it('inverts the map from planet center to flow center', () => {
    const px = 10
    const py = 20
    const cx = px + PLANET_CELL_CENTER_OFFSET
    const cy = -(py + PLANET_CELL_CENTER_OFFSET)
    const back = flowCenterToPlanet(cx, cy)
    expect(back.px).toBeCloseTo(px)
    expect(back.py).toBeCloseTo(py)
  })
})

describe('buildPlanetSpatialGrid', () => {
  it('returns null for empty input', () => {
    expect(buildPlanetSpatialGrid([])).toBeNull()
  })

  it('places a single planet in one bucket', () => {
    const g = buildPlanetSpatialGrid([{ id: 'a', x: 5, y: 5 }])
    expect(g).not.toBeNull()
    expect(g!.buckets.size).toBe(1)
  })
})

describe('findClosestPlanetWithinRadius', () => {
  it('finds the only planet within radius', () => {
    const g = buildPlanetSpatialGrid([
      { id: 'a', x: 0, y: 0 },
      { id: 'b', x: 100, y: 100 },
    ])
    expect(g).not.toBeNull()
    const id = findClosestPlanetWithinRadius(g!, 0.2, 0.2, 1)
    expect(id).toBe('a')
  })

  it('returns null when no planet is within radius', () => {
    const g = buildPlanetSpatialGrid([
      { id: 'a', x: 0, y: 0 },
      { id: 'b', x: 100, y: 100 },
    ])
    const id = findClosestPlanetWithinRadius(g!, 50, 50, 1)
    expect(id).toBeNull()
  })

  it('prefers the closest of two nearby planets', () => {
    const g = buildPlanetSpatialGrid([
      { id: 'near', x: 10, y: 10 },
      { id: 'far', x: 12, y: 10 },
    ])
    const id = findClosestPlanetWithinRadius(g!, 10.2, 10, 5)
    expect(id).toBe('near')
  })

  it('handles many collinear planets without a pathological cell count', () => {
    const nodes = Array.from({ length: 400 }, (_, i) => ({
      id: `p-${i}`,
      x: i,
      y: 0,
    }))
    const g = buildPlanetSpatialGrid(nodes)
    expect(g).not.toBeNull()
    expect(g!.cellSize).toBeGreaterThan(1e-3)
    const id = findClosestPlanetWithinRadius(g!, 200.05, 0, 0.2)
    expect(id).toBe('p-200')
  })
})
