import { describe, expect, it } from 'vitest'
import { hexWithAlpha } from './cartographyColor'
import {
  buildBlackHoleErgosphereGradientStops,
  buildBlackHolePaneShape,
} from './blackHoleOverlay'
import { ERGOSPHERE_BAND_COUNT } from './blackHoles'
import { blackHoleErgosphereBandGrey } from './stellarCartographyTheme'

describe('buildBlackHoleErgosphereGradientStops', () => {
  it('places band boundaries at host radii with inner and outer greys', () => {
    const coreRadiusLy = 15
    const bandWidthLy = 4
    const stops = buildBlackHoleErgosphereGradientStops(coreRadiusLy, bandWidthLy)
    const outerLy = coreRadiusLy + ERGOSPHERE_BAND_COUNT * bandWidthLy

    expect(stops[0]).toEqual({ offset: 0, color: '#000000', opacity: 1 })
    expect(stops.find((s) => s.offset === coreRadiusLy / outerLy && s.color === '#000000')).toBeDefined()
    expect(
      stops.find(
        (s) =>
          s.offset === coreRadiusLy / outerLy &&
          s.color === blackHoleErgosphereBandGrey(1)
      )
    ).toBeDefined()
    expect(stops.at(-1)).toEqual({
      offset: 1,
      color: blackHoleErgosphereBandGrey(9),
      opacity: 0.3,
    })
  })
})

describe('buildBlackHolePaneShape', () => {
  it('builds one ergosphere gradient shape with outer cyan halo radii', () => {
    const viewport = {
      width: 800,
      height: 600,
      tx: 400,
      ty: 300,
      scale: 4,
    }
    const shape = buildBlackHolePaneShape(
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
      viewport
    )

    expect(shape).not.toBeNull()
    expect(shape?.key).toBe('bh-1')
    expect(shape?.ergosphereGradientId).toBe('bh-1-ergo-grad')
    expect(shape?.coreR).toBeCloseTo(15 * viewport.scale)
    expect(shape?.ergosphereR).toBeCloseTo(51 * viewport.scale)
    expect(shape?.haloR).toBeCloseTo(56 * viewport.scale)
    expect(shape?.ergosphereEdgeOffset).toBeCloseTo(51 / 56)
    expect(shape?.ergosphereStops.length).toBeGreaterThan(0)

    const band1Grey = hexWithAlpha(blackHoleErgosphereBandGrey(1), 0.3)
    const band9Grey = hexWithAlpha(blackHoleErgosphereBandGrey(9), 0.3)
    expect(
      shape?.ergosphereStops.some(
        (stop) =>
          stop.color === blackHoleErgosphereBandGrey(1) && stop.opacity === 0.3
      )
    ).toBe(true)
    expect(
      shape?.ergosphereStops.some(
        (stop) =>
          stop.color === blackHoleErgosphereBandGrey(9) && stop.opacity === 0.3
      )
    ).toBe(true)
    expect(band1Grey).toBe('rgba(26, 26, 26, 0.3)')
    expect(band9Grey).toBe('rgba(74, 74, 74, 0.3)')
  })
})
