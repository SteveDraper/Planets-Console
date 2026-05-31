import { describe, expect, it } from 'vitest'
import { hexWithAlpha } from './cartographyColor'
import {
  BLACK_HOLE_CONCEPT_CONSTANTS,
  buildBlackHoleErgosphereGradientStops,
  buildBlackHolePaneShape,
} from './blackHoleOverlay'
import { blackHoleErgosphereBandGrey } from './stellarCartographyTheme'

const blackHoleConstants = BLACK_HOLE_CONCEPT_CONSTANTS

describe('buildBlackHoleErgosphereGradientStops', () => {
  it('places band boundaries at host radii with inner and outer greys', () => {
    const coreRadiusLy = 15
    const bandWidthLy = 4
    const outerLy =
      coreRadiusLy + blackHoleConstants.ergosphereBandCount * bandWidthLy
    const stops = buildBlackHoleErgosphereGradientStops(
      blackHoleConstants,
      coreRadiusLy,
      bandWidthLy,
      outerLy
    )

    expect(stops[0]).toEqual({ offset: 0, color: '#000000', opacity: 1 })
    expect(stops.find((s) => s.offset === coreRadiusLy / outerLy && s.color === '#000000')).toBeDefined()
    expect(
      stops.find(
        (s) =>
          s.offset === coreRadiusLy / outerLy &&
          s.color === blackHoleErgosphereBandGrey(1, blackHoleConstants.ergosphereBandCount)
      )
    ).toBeDefined()
    expect(stops.at(-1)).toEqual({
      offset: 1,
      color: blackHoleErgosphereBandGrey(9, blackHoleConstants.ergosphereBandCount),
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
      blackHoleConstants,
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
    expect(shape?.haloR).toBeCloseTo((51 + blackHoleConstants.haloExtraLy) * viewport.scale)
    expect(shape?.ergosphereEdgeOffset).toBeCloseTo(
      51 / (51 + blackHoleConstants.haloExtraLy)
    )
    expect(shape?.ergosphereStops.length).toBeGreaterThan(0)

    const band1Grey = hexWithAlpha(
      blackHoleErgosphereBandGrey(1, blackHoleConstants.ergosphereBandCount),
      0.3
    )
    const band9Grey = hexWithAlpha(
      blackHoleErgosphereBandGrey(9, blackHoleConstants.ergosphereBandCount),
      0.3
    )
    expect(
      shape?.ergosphereStops.some(
        (stop) =>
          stop.color ===
            blackHoleErgosphereBandGrey(1, blackHoleConstants.ergosphereBandCount) &&
          stop.opacity === 0.3
      )
    ).toBe(true)
    expect(
      shape?.ergosphereStops.some(
        (stop) =>
          stop.color ===
            blackHoleErgosphereBandGrey(9, blackHoleConstants.ergosphereBandCount) &&
          stop.opacity === 0.3
      )
    ).toBe(true)
    expect(band1Grey).toBe('rgba(26, 26, 26, 0.3)')
    expect(band9Grey).toBe('rgba(74, 74, 74, 0.3)')
  })
})
