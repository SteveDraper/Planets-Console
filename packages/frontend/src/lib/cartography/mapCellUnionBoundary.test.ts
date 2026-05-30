import { describe, expect, it } from 'vitest'
import { MAP_CELL_SIZE_LY, mapCellUnionBoundarySegments } from './mapCellUnionBoundary'
import { starClusterRadiationSumAt } from './starClusterRadiation'

describe('mapCellUnionBoundary', () => {
  const body = { x: 100, y: 100, radius: 5, temp: 10_000, mass: 10_000 }

  it('excludes cells whose sample index has zero flux', () => {
    const halo = Math.sqrt(body.mass)
    const outerActiveCellX = body.x + Math.floor(halo) - 1
    const inactiveNeighborCellX = outerActiveCellX + 1
    expect(starClusterRadiationSumAt(outerActiveCellX, body.y, [body])).toBeGreaterThan(0)
    expect(starClusterRadiationSumAt(inactiveNeighborCellX, body.y, [body])).toBe(0)

    const bounds = {
      minX: outerActiveCellX - 2,
      maxX: inactiveNeighborCellX + 2,
      minY: body.y - 2,
      maxY: body.y + 2,
    }
    const segments = mapCellUnionBoundarySegments([body], bounds)
    const maxX = Math.max(...segments.flatMap(([start, end]) => [start.x, end.x]))
    expect(maxX).toBeLessThanOrEqual(outerActiveCellX + MAP_CELL_SIZE_LY + 1e-6)
  })

  it('does not include inactive neighbor cells in the union', () => {
    const activeCellX = 199
    const inactiveCellX = 200
    expect(starClusterRadiationSumAt(activeCellX, body.y, [body])).toBeGreaterThan(0)
    expect(starClusterRadiationSumAt(inactiveCellX, body.y, [body])).toBe(0)

    const bounds = {
      minX: activeCellX - 1,
      maxX: inactiveCellX + 1,
      minY: body.y - 1,
      maxY: body.y + 1,
    }
    const segments = mapCellUnionBoundarySegments([body], bounds)
    const maxX = Math.max(...segments.flatMap(([start, end]) => [start.x, end.x]))
    expect(maxX).toBeLessThanOrEqual(activeCellX + MAP_CELL_SIZE_LY + 1e-6)
  })

  it('traces boundaries on integer cell edges, not through cell centers', () => {
    const bounds = {
      minX: body.x - 5,
      maxX: body.x + Math.sqrt(body.mass) + 5,
      minY: body.y - 5,
      maxY: body.y + 5,
    }
    const segments = mapCellUnionBoundarySegments([body], bounds)
    expect(segments.length).toBeGreaterThan(0)
    for (const [start, end] of segments) {
      expect(Number.isInteger(start.x)).toBe(true)
      expect(Number.isInteger(start.y)).toBe(true)
      expect(Number.isInteger(end.x)).toBe(true)
      expect(Number.isInteger(end.y)).toBe(true)
    }
  })
})
