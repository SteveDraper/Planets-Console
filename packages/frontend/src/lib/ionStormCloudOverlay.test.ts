import { describe, expect, it, beforeEach } from 'vitest'
import {
  buildIonVoltageGrid,
  clearIonStormCloudRasterCache,
  findComponentsAtMinClass,
  findComponentsAtThreshold,
  groupIonStormsByRoot,
  ionStormBoundaryPathFromPolygons,
  ionStormBoundaryPolygonsAtThreshold,
  ionVoltageAt,
} from './ionStormCloudOverlay'
import { gridValueAt } from './scalarFieldGrid'
import {
  ION_STORM_CLASS_VOLTAGE_THRESHOLDS,
  ION_STORM_OUTER_VOLTAGE_THRESHOLD,
} from './stellarCartographyTheme'
import contractFixture from '../test/fixtures/ion_voltage_contract.json'

/** Host-aligned golden vectors; keep in sync with packages/api/tests/fixtures/ion_voltage_contract.json */
describe('ion voltage contract fixture', () => {
  const gridTolerance = contractFixture.gridTolerance

  it('matches buildIonVoltageGrid and ionVoltageAt at fixture cells', () => {
    for (const testCase of contractFixture.cases) {
      const grid = buildIonVoltageGrid(
        testCase.circles,
        testCase.bounds,
        testCase.gridStep,
        testCase.cloudy
      )

      for (const sample of testCase.samples) {
        const direct = ionVoltageAt(testCase.circles, sample.x, sample.y, testCase.cloudy)
        expect(direct).toBeCloseTo(sample.expectedVoltage, 10)

        const col = Math.round((sample.x - testCase.bounds.minX) / testCase.gridStep)
        const row = Math.round((sample.y - testCase.bounds.minY) / testCase.gridStep)
        if (col >= 0 && row >= 0 && col < grid.cols && row < grid.rows) {
          const gridVoltage = gridValueAt(grid, col, row)
          expect(Math.abs(gridVoltage - sample.expectedVoltage)).toBeLessThanOrEqual(gridTolerance)
        }
      }
    }
  })
})

describe('ionStormCloudOverlay', () => {
  beforeEach(() => {
    clearIonStormCloudRasterCache()
  })

  const cloudyGroup = [
    { layer: 'ion-storms' as const, id: 'is-17', x: 100, y: 200, radius: 50, voltage: 120, class: 3, parentId: 0 },
    { layer: 'ion-storms' as const, id: 'is-19', x: 130, y: 210, radius: 40, voltage: 160, class: 4, parentId: 17 },
  ]

  it('groups ion storm overlay circles by root parentId', () => {
    const grouped = groupIonStormsByRoot(cloudyGroup)
    expect(grouped.size).toBe(1)
    expect(grouped.get(17)?.circles).toHaveLength(2)
  })

  it('sums cloudy voltage from overlapping sub-circles', () => {
    const circles = [
      { x: 0, y: 0, radius: 50, voltage: 120 },
      { x: 200, y: 0, radius: 40, voltage: 160 },
    ]
    expect(ionVoltageAt(circles, 0, 0, true)).toBeCloseTo(120)
    expect(ionVoltageAt(circles, 200, 0, true)).toBeCloseTo(160)
    expect(ionVoltageAt(circles, 1000, 1000, true)).toBe(0)
  })

  it('uses flat center voltage in classic mode', () => {
    const circles = [{ x: 0, y: 0, radius: 20, voltage: 130 }]
    expect(ionVoltageAt(circles, 0, 0, false)).toBe(130)
    expect(ionVoltageAt(circles, 19, 0, false)).toBe(130)
    expect(ionVoltageAt(circles, 21, 0, false)).toBe(0)
  })

  it('builds smooth outer and class iso-contours for cloudy storms', () => {
    const circles = groupIonStormsByRoot(cloudyGroup).get(17)!.circles
    const bounds = { minX: 50, minY: 150, maxX: 180, maxY: 260 }
    const viewport = { width: 800, height: 600, tx: 400, ty: 300, scale: 4 }

    const outer = ionStormBoundaryPolygonsAtThreshold(
      circles,
      bounds,
      true,
      ION_STORM_OUTER_VOLTAGE_THRESHOLD
    )
    expect(outer.length).toBeGreaterThan(0)
    expect(outer[0]!.length).toBeGreaterThan(100)

    for (const threshold of ION_STORM_CLASS_VOLTAGE_THRESHOLDS) {
      if (threshold > 160) continue
      const polygons = ionStormBoundaryPolygonsAtThreshold(circles, bounds, true, threshold)
      expect(polygons.length).toBeGreaterThan(0)
    }

    const outerPaths = ionStormBoundaryPathFromPolygons(outer, viewport)
    expect(outerPaths.length).toBeGreaterThan(0)
    expect(outerPaths[0]).toMatch(/^M /)
    expect(outerPaths[0]).toMatch(/ Z$/)
  })

  it('outlines disjoint class-2 islands with separate bounded polygons', () => {
    const circles = [
      { x: 0, y: 0, radius: 80, voltage: 35 },
      { x: -40, y: 30, radius: 12, voltage: 95 },
      { x: 45, y: -25, radius: 12, voltage: 95 },
    ]
    const bounds = { minX: -92, minY: -37, maxX: 92, maxY: 87 }
    const grid = buildIonVoltageGrid(circles, bounds, 1, true)
    expect(findComponentsAtMinClass(grid, 2).length).toBeGreaterThanOrEqual(2)
    const polygons = ionStormBoundaryPolygonsAtThreshold(circles, bounds, true, 50, grid)
    expect(polygons.length).toBeGreaterThanOrEqual(2)
  })

  it('finds separate outer components by voltage threshold', () => {
    const circles = [
      { x: 0, y: 0, radius: 10, voltage: 80 },
      { x: 100, y: 0, radius: 10, voltage: 80 },
    ]
    const bounds = { minX: -10, minY: -10, maxX: 110, maxY: 10 }
    const grid = buildIonVoltageGrid(circles, bounds, 1, true)
    expect(findComponentsAtThreshold(grid, ION_STORM_OUTER_VOLTAGE_THRESHOLD).length).toBe(2)
  })

  it('draws outer edge for classic flat storms without internal class rings', () => {
    const circles = [{ x: 0, y: 0, radius: 30, voltage: 130 }]
    const bounds = { minX: -30, minY: -30, maxX: 30, maxY: 30 }
    expect(ionStormBoundaryPolygonsAtThreshold(circles, bounds, false, 150).length).toBe(0)
    expect(
      ionStormBoundaryPolygonsAtThreshold(circles, bounds, false, ION_STORM_OUTER_VOLTAGE_THRESHOLD).length
    ).toBe(1)
  })
})
