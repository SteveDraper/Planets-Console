import { beforeEach, describe, expect, it } from 'vitest'
import { mapBoundsFromCircles } from './cartographyOverlayGeometry'
import {
  buildNeutronClusterFluxBoundaryPaths,
  clearNeutronClusterFluxRasterCache,
  neutronClusterFluxPaneShapeToRasterField,
} from './neutronClusterFluxOverlay'
import { starClusterHaloRadiusLy } from './starClusterRadiation'

describe('neutronClusterFluxOverlay', () => {
  beforeEach(() => {
    clearNeutronClusterFluxRasterCache()
  })

  const viewport = {
    width: 800,
    height: 600,
    tx: 400,
    ty: 300,
    scale: 4,
  }

  const bithBodies = [
    { x: 0, y: 0, radius: 5, temp: 10_000, mass: 10_000 },
    { x: 3, y: 0, radius: 5, temp: 10_000, mass: 10_000 },
  ]

  const bounds = mapBoundsFromCircles(
    bithBodies.map((body) => ({
      x: body.x,
      y: body.y,
      radius: starClusterHaloRadiusLy(body.mass),
    }))
  )!

  it('draws merged flux boundary paths for overlapping cluster halos', () => {
    const boundaryPaths = buildNeutronClusterFluxBoundaryPaths(bithBodies, bounds, viewport)
    expect(boundaryPaths.length).toBeGreaterThan(0)
    expect(boundaryPaths[0]?.length).toBeGreaterThan(0)
    expect(boundaryPaths[0]).toContain('M ')
  })

  it('maps boundary paths into raster overlay stroke paths', () => {
    const boundaryPaths = buildNeutronClusterFluxBoundaryPaths(bithBodies, bounds, viewport)
    const raster = neutronClusterFluxPaneShapeToRasterField({
      key: 'nc-flux-Bith',
      left: 0,
      top: 0,
      width: 100,
      height: 100,
      imageDataUrl: 'data:image/png;base64,test',
      fillClipPathId: 'clip',
      boundaryPaths,
      stroke: 'rgba(125, 211, 252, 0.6)',
      strokeWidth: 0.5,
    })
    expect(raster.strokePaths).toHaveLength(boundaryPaths.length)
  })
})
