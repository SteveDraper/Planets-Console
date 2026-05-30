import { describe, expect, it, beforeEach } from 'vitest'
import {
  buildDensityGrid,
  clearNebulaCloudRasterCache,
  groupNebulaCentersByName,
  nebulaBoundaryPathFromCenters,
  nebulaBoundaryPathFromPolylines,
  nebulaBoundaryPathFromSegments,
  nebulaBoundaryPolygonFromCenters,
  nebulaBoundaryPolylinesFromGrid,
  nebulaCloudFillOpacityAt,
  nebulaCloudOpacityAt,
  nebulaDensityAt,
  mapLyToSampleCell,
  nebulaHostDensityAt,
  nebulaVisibilityAt,
  isPointInsideMapPolygon,
  soloNebulaBoundaryRadius,
  type NebulaCloudCenter,
} from './nebulaCloudOverlay'
import { stitchMapSegmentsToPolylines, type MapSegment } from './cartographyPathUtils'
import {
  NEBULA_BOUNDARY_DENSITY_THRESHOLD,
  NEBULA_DENSE_VISIBILITY_LY,
  NEBULA_FILL_SPARSE_VISIBILITY_LY,
  nebulaFillOpacityFromHostDensity,
  nebulaFillOpacityFromVisibility,
  nebulaVisibilityLyFromDensity,
} from './stellarCartographyTheme'

describe('nebulaCloudOverlay', () => {
  beforeEach(() => {
    clearNebulaCloudRasterCache()
  })

  const zoieCenters: NebulaCloudCenter[] = [
    { x: 100, y: 200, radius: 50, intensity: 20 },
    { x: 130, y: 210, radius: 40, intensity: 12 },
  ]

  it('groups nebula overlay circles by name', () => {
    const grouped = groupNebulaCentersByName([
      { layer: 'nebulae', id: '1', x: 1, y: 2, radius: 3, name: 'Zoie', intensity: 6 },
      { layer: 'nebulae', id: '2', x: 4, y: 5, radius: 6, name: 'Zoie', intensity: 8 },
      { layer: 'nebulae', id: '3', x: 7, y: 8, radius: 9, name: 'Eagle', intensity: 10 },
    ])
    expect(grouped.get('Zoie')).toHaveLength(2)
    expect(grouped.get('Eagle')).toHaveLength(1)
  })

  it('sums falloff density from overlapping centers', () => {
    const single = nebulaDensityAt([zoieCenters[0]!], 100, 200)
    const combined = nebulaDensityAt(zoieCenters, 100, 200)
    const outside = nebulaDensityAt(zoieCenters, 1000, 1000)
    expect(single).toBeCloseTo(20)
    expect(combined).toBeGreaterThan(20)
    expect(outside).toBe(0)
  })

  it('uses CEIL per center for host density', () => {
    const centers: NebulaCloudCenter[] = [{ x: 0, y: 0, radius: 100, intensity: 6 }]
    const host = nebulaHostDensityAt(centers, 99, 0)
    const falloff = nebulaDensityAt(centers, 99, 0)
    expect(falloff).toBeGreaterThan(0)
    expect(falloff).toBeLessThan(1)
    expect(host).toBe(1)
  })

  it('maps higher host density to lower visibility and higher fill opacity', () => {
    const dense = nebulaHostDensityAt(zoieCenters, 100, 200)
    const sparse = nebulaHostDensityAt(zoieCenters, 145, 200)
    expect(nebulaVisibilityAt(dense)).toBeLessThan(nebulaVisibilityAt(sparse))
    expect(nebulaCloudOpacityAt(dense, 100, 200)).toBeGreaterThan(
      nebulaCloudOpacityAt(sparse, 145, 200)
    )
  })

  it('maps continuous map ly to the same sample cell as hover sampling', () => {
    expect(mapLyToSampleCell(1941.5, 2283.5)).toEqual({ cellX: 1941, cellY: 2283 })
    expect(mapLyToSampleCell(1941.2, 2283.8)).toEqual({ cellX: 1941, cellY: 2283 })
  })

  it('matches tooltip visibility at representative densities', () => {
    expect(nebulaVisibilityLyFromDensity(72)).toBe(55)
    expect(nebulaVisibilityLyFromDensity(39)).toBe(100)
    expect(nebulaFillOpacityFromHostDensity(72)).toBeGreaterThan(
      nebulaFillOpacityFromHostDensity(39)
    )
    expect(nebulaCloudOpacityAt(72, 0, 0)).toBeGreaterThan(nebulaCloudOpacityAt(39, 0, 0))
  })

  it('does not render fill where host density is zero', () => {
    const centers: NebulaCloudCenter[] = [{ x: 0, y: 0, radius: 10, intensity: 20 }]
    expect(nebulaHostDensityAt(centers, 11, 0)).toBe(0)
    expect(nebulaCloudFillOpacityAt(0, 11, 0)).toBe(0)
    expect(nebulaCloudFillOpacityAt(nebulaHostDensityAt(centers, 0, 0), 0, 0)).toBeGreaterThan(0)
  })

  it('masks fill samples outside the analytic boundary polygon', () => {
    const centers: NebulaCloudCenter[] = [{ x: 0, y: 0, radius: 10, intensity: 20 }]
    const polygon = nebulaBoundaryPolygonFromCenters(centers)
    const boundaryRadius = soloNebulaBoundaryRadius(centers[0]!, NEBULA_BOUNDARY_DENSITY_THRESHOLD)
    expect(boundaryRadius).not.toBeNull()
    const radius = boundaryRadius as number
    const outsideButHazy = radius + 0.05
    expect(isPointInsideMapPolygon(0, 0, polygon)).toBe(true)
    expect(isPointInsideMapPolygon(radius - 0.05, 0, polygon)).toBe(true)
    expect(isPointInsideMapPolygon(outsideButHazy, 0, polygon)).toBe(false)
    expect(nebulaDensityAt(centers, outsideButHazy, 0)).toBeGreaterThan(0)
    expect(nebulaDensityAt(centers, outsideButHazy, 0)).toBeLessThan(
      NEBULA_BOUNDARY_DENSITY_THRESHOLD
    )
  })

  it('spreads fill opacity across the 45–200 ly render range', () => {
    expect(nebulaFillOpacityFromVisibility(NEBULA_DENSE_VISIBILITY_LY)).toBeCloseTo(0.55)
    expect(nebulaFillOpacityFromVisibility(NEBULA_FILL_SPARSE_VISIBILITY_LY)).toBeCloseTo(0.06)
    expect(nebulaFillOpacityFromVisibility(54)).toBeGreaterThan(
      nebulaFillOpacityFromVisibility(100)
    )
    expect(nebulaFillOpacityFromVisibility(100)).toBeGreaterThan(0.06)
    expect(nebulaFillOpacityFromVisibility(200)).toBeCloseTo(0.06)
  })

  it('builds a solo circle boundary as one SVG arc path', () => {
    const centers: NebulaCloudCenter[] = [{ x: 0, y: 0, radius: 10, intensity: 20 }]
    const soloRadius = soloNebulaBoundaryRadius(centers[0]!, NEBULA_BOUNDARY_DENSITY_THRESHOLD)
    expect(soloRadius).toBeCloseTo(9.9)
    const path = nebulaBoundaryPathFromCenters(centers, {
      width: 800,
      height: 600,
      tx: 400,
      ty: 300,
      scale: 4,
    })
    expect(path.startsWith('M ')).toBe(true)
    expect(path.endsWith(' Z')).toBe(true)
    expect(path).toContain('A ')
    expect(path.split(' M ').length).toBe(1)
  })

  it('builds one continuous analytic boundary for overlapping centers', () => {
    const polygon = nebulaBoundaryPolygonFromCenters(zoieCenters)
    expect(polygon.length).toBeGreaterThan(100)
    const path = nebulaBoundaryPathFromCenters(zoieCenters, {
      width: 800,
      height: 600,
      tx: 400,
      ty: 300,
      scale: 8,
    })
    expect(path.split(' M ').length).toBe(1)
    expect(path.endsWith(' Z')).toBe(true)
    for (const point of polygon) {
      expect(nebulaDensityAt(zoieCenters, point.x, point.y)).toBeGreaterThanOrEqual(
        NEBULA_BOUNDARY_DENSITY_THRESHOLD - 0.05
      )
    }
  })

  it('projects map-space boundary segments when the viewport changes', () => {
    const centers: NebulaCloudCenter[] = [{ x: 0, y: 0, radius: 10, intensity: 20 }]
    const grid = buildDensityGrid(centers, { minX: -10, minY: -10, maxX: 10, maxY: 10 }, 1)
    const polylines = nebulaBoundaryPolylinesFromGrid(grid, centers)
    const viewportA = { width: 800, height: 600, tx: 400, ty: 300, scale: 4 }
    const viewportB = { width: 800, height: 600, tx: 200, ty: 150, scale: 2 }
    const pathA = nebulaBoundaryPathFromPolylines(polylines, viewportA)
    const pathB = nebulaBoundaryPathFromPolylines(polylines, viewportB)
    expect(pathA.length).toBeGreaterThan(0)
    expect(pathB.length).toBeGreaterThan(0)
    expect(pathA).not.toBe(pathB)
  })

  it('stitches shared endpoints into one polyline path', () => {
    const segments: MapSegment[] = [
      [{ x: 0, y: 0 }, { x: 1, y: 0 }],
      [{ x: 1, y: 0 }, { x: 1, y: 1 }],
      [{ x: 1, y: 1 }, { x: 0, y: 1 }],
      [{ x: 0, y: 1 }, { x: 0, y: 0 }],
    ]
    const polylines = stitchMapSegmentsToPolylines(segments)
    expect(polylines).toHaveLength(1)
    const path = nebulaBoundaryPathFromSegments(segments, {
      width: 100,
      height: 100,
      tx: 0,
      ty: 0,
      scale: 10,
    })
    expect(path.split(' M ').length).toBe(1)
    expect(path.endsWith(' Z')).toBe(true)
  })
})
