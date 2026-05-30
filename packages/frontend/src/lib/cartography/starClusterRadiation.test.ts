import { describe, expect, it } from 'vitest'
import { mapLyToSampleCell } from '../planetSpatialGrid'
import {
  starClusterRadiationAt,
  starClusterRadiationHostSumAt,
  starClusterRadiationSumAt,
} from './starClusterRadiation'

describe('starClusterRadiation', () => {
  const body = { x: 100, y: 100, radius: 5, temp: 10_000, mass: 10_000 }

  it('returns zero inside the lethal core', () => {
    expect(starClusterRadiationAt(100, 100, body)).toBe(0)
  })

  it('sums contributions from multiple bodies in one cluster', () => {
    const second = { ...body, x: 103 }
    const single = starClusterRadiationAt(115, 100, body)
    const sum = starClusterRadiationSumAt(115, 100, [body, second])
    expect(sum).toBeGreaterThan(single)
  })

  it('uses planet-grid host sampling so the rim matches hover flux', () => {
    const halo = Math.sqrt(body.mass)
    const outerActiveCell = body.x + Math.floor(halo) - 1
    const inactiveCell = outerActiveCell + 1
    expect(starClusterRadiationAt(outerActiveCell, body.y, body)).toBeGreaterThan(0)
    expect(starClusterRadiationAt(inactiveCell, body.y, body)).toBe(0)
    expect(mapLyToSampleCell(outerActiveCell + 0.5, body.y)).toEqual({
      cellX: outerActiveCell,
      cellY: body.y,
    })
    expect(starClusterRadiationHostSumAt(outerActiveCell + 0.5, body.y, [body])).toBeGreaterThan(0)
    expect(starClusterRadiationHostSumAt(inactiveCell + 0.5, body.y, [body])).toBe(0)
  })
})
