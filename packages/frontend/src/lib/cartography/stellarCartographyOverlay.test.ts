import { describe, expect, it } from 'vitest'
import {
  buildStellarCartographyOverlayPaneShapes,
  flowLySpanToPanePixels,
  gameMapCellCenterToFlow,
  ionStormArrowEndpointFlow,
  wormholeEndpointDiameterPx,
} from './stellarCartographyOverlay'
import { WORMHOLE_ENDPOINT_MIN_DIAMETER_PX } from './stellarCartographyTheme'

describe('stellarCartographyOverlay', () => {
  it('projects map cell centers to flow space with 0.5 offset', () => {
    expect(gameMapCellCenterToFlow(10, 20)).toEqual({ cx: 10.5, cy: -20.5 })
  })

  it('draws ion storm arrows with warp-squared length and north heading', () => {
    const { x1, y1, x2, y2 } = ionStormArrowEndpointFlow(100, 200, 0, 5)
    expect(x1).toBeCloseTo(100.5)
    expect(y1).toBeCloseTo(-200.5)
    expect(x2).toBeCloseTo(100.5)
    expect(y2).toBeCloseTo(-225.5)
  })

  it('draws east heading with positive flow x delta', () => {
    const { x2, y2 } = ionStormArrowEndpointFlow(0, 0, 90, 3)
    expect(x2).toBeCloseTo(9.5)
    expect(y2).toBeCloseTo(-0.5)
  })

  it('draws debris disk borders as outline-only circles', () => {
    const viewport = {
      width: 800,
      height: 600,
      tx: 400,
      ty: 300,
      scale: 4,
    }
    const shapes = buildStellarCartographyOverlayPaneShapes(
      [
        {
          layer: 'debris-disks',
          id: 'dd-1',
          x: 0,
          y: 0,
          radius: 20,
        },
      ],
      [],
      viewport
    )
    expect(shapes.circles).toHaveLength(0)
    expect(shapes.debrisDiskBorders).toHaveLength(1)
    expect(shapes.debrisDiskBorders[0]?.fill).toBe('none')
    expect(shapes.debrisDiskBorders[0]?.stroke).toBe('#dc2626')
  })

  it('builds pane shapes for visible overlay circles', () => {
    const viewport = {
      width: 800,
      height: 600,
      tx: 400,
      ty: 300,
      scale: 4,
    }
    const { cx, cy } = gameMapCellCenterToFlow(5, 5)
    const expectedDiameter = wormholeEndpointDiameterPx(cx, cy, viewport)
    const shapes = buildStellarCartographyOverlayPaneShapes(
      [
        {
          layer: 'ion-storms',
          id: 'is-1',
          x: 0,
          y: 0,
          radius: 10,
          class: 2,
          parentId: 0,
          voltage: 80,
          heading: 0,
          warp: 5,
        },
      ],
      [{ x: 5, y: 5 }],
      viewport,
      { cloudyIonStorms: true }
    )
    expect(shapes.circles).toHaveLength(0)
    expect(shapes.arrows).toHaveLength(1)
    expect(shapes.wormholeMarkers).toHaveLength(1)
    expect(shapes.wormholeMarkers[0]?.diameterPx).toBeCloseTo(expectedDiameter)
  })

  it('measures map span in pane pixels the same way as annuli and warp wells', () => {
    const viewport = {
      width: 800,
      height: 600,
      tx: 100,
      ty: 50,
      scale: 12,
    }
    expect(flowLySpanToPanePixels(10.5, -20.5, 5, viewport)).toBeCloseTo(60)
    expect(flowLySpanToPanePixels(10.5, -20.5, 7, viewport)).toBeCloseTo(84)
  })

  it('never renders wormhole icons smaller than at 300% slider zoom', () => {
    const viewport = {
      width: 800,
      height: 600,
      tx: 100,
      ty: 50,
      scale: 0.2,
    }
    const { cx, cy } = gameMapCellCenterToFlow(0, 0)
    expect(wormholeEndpointDiameterPx(cx, cy, viewport)).toBe(WORMHOLE_ENDPOINT_MIN_DIAMETER_PX)
    expect(WORMHOLE_ENDPOINT_MIN_DIAMETER_PX).toBe(15)
  })

  it('draws star cluster radiation halo as a gradient annulus', () => {
    const viewport = {
      width: 800,
      height: 600,
      tx: 400,
      ty: 300,
      scale: 4,
    }
    const shapes = buildStellarCartographyOverlayPaneShapes(
      [
        {
          layer: 'star-clusters',
          id: 'star-1',
          x: 0,
          y: 0,
          radius: 42,
          temp: 28601,
          mass: 6256,
          name: 'Gores',
        },
      ],
      [],
      viewport
    )
    expect(shapes.circles).toHaveLength(0)
    expect(shapes.annuli).toHaveLength(1)
    expect(shapes.annuli[0]?.bandGradient?.peakOpacity).toBeGreaterThan(
      shapes.annuli[0]?.bandGradient?.edgeOpacity ?? 0
    )
    expect(shapes.annuli[0]?.bandGradient?.edgeOpacity).toBeGreaterThan(0)
    expect(shapes.annuli[0]?.coreGradient?.peakOpacity).toBeGreaterThan(
      shapes.annuli[0]?.coreGradient?.edgeOpacity ?? 0
    )
    expect(shapes.annuli[0]?.coreStroke).toBeTruthy()
    expect(shapes.annuli[0]?.bandR).toBeGreaterThan(shapes.annuli[0]?.coreR ?? 0)
  })

  it('omits star cluster rim strokes in no-outline display mode', () => {
    const viewport = {
      width: 800,
      height: 600,
      tx: 400,
      ty: 300,
      scale: 4,
    }
    const shapes = buildStellarCartographyOverlayPaneShapes(
      [
        {
          layer: 'star-clusters',
          id: 'star-1',
          x: 0,
          y: 0,
          radius: 42,
          temp: 28601,
          mass: 6256,
          name: 'Gores',
        },
      ],
      [],
      viewport,
      { starClusterDisplayMode: 'no-outline' }
    )
    expect(shapes.annuli[0]?.coreStroke).toBeUndefined()
    expect(shapes.annuli[0]?.bandStroke).toBe('none')
  })

  it('draws black hole ergosphere as nine grey band annuli with outer cyan halo', () => {
    const viewport = {
      width: 800,
      height: 600,
      tx: 400,
      ty: 300,
      scale: 4,
    }
    const shapes = buildStellarCartographyOverlayPaneShapes(
      [
        {
          layer: 'black-holes',
          id: 'bh-1',
          x: 0,
          y: 0,
          radius: 51,
          coreRadius: 15,
          bandRadius: 4,
          name: 'Solace',
        },
      ],
      [],
      viewport
    )
    expect(shapes.annuli).toHaveLength(9)
    expect(shapes.blackHoleHalos).toHaveLength(1)
    expect(shapes.annuli[0]?.key).toBe('bh-1-band-9')
    expect(shapes.annuli[8]?.key).toBe('bh-1-band-1')
    expect(shapes.annuli[0]?.bandFill).toBe('rgba(74, 74, 74, 0.3)')
    expect(shapes.annuli[8]?.bandFill).toBe('rgba(26, 26, 26, 0.3)')
    expect(shapes.annuli[0]?.bandGradient).toBeUndefined()
    expect(shapes.annuli[8]?.coreR).toBeCloseTo(15 * viewport.scale)
    expect(shapes.annuli[0]?.bandR).toBeCloseTo(51 * viewport.scale)
    expect(shapes.blackHoleHalos[0]?.r).toBeCloseTo(56 * viewport.scale)
    expect(shapes.blackHoleHalos[0]?.ergosphereEdgeOffset).toBeCloseTo(51 / 56)
    expect(shapes.annuli[0]?.bandStroke).toBe('none')
  })

  it('draws neutron cluster flux as raster and blue cores without per-star annuli', () => {
    const viewport = {
      width: 800,
      height: 600,
      tx: 400,
      ty: 300,
      scale: 4,
    }
    const shapes = buildStellarCartographyOverlayPaneShapes(
      [
        {
          layer: 'neutron-clusters',
          id: 'star-1',
          name: 'Bith',
          x: 0,
          y: 0,
          radius: 5,
          temp: 10_000,
          mass: 10_000,
        },
        {
          layer: 'neutron-clusters',
          id: 'star-2',
          name: 'Bith',
          x: 3,
          y: 0,
          radius: 5,
          temp: 10_000,
          mass: 10_000,
        },
      ],
      [],
      viewport
    )
    expect(shapes.annuli).toHaveLength(0)
    expect(shapes.circles).toHaveLength(2)
    expect(shapes.circles[0]?.fillGradient?.color.startsWith('#')).toBe(true)
  })
})
