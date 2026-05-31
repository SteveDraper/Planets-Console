import { describe, expect, it } from 'vitest'
import {
  applyFutureIonStormOverlayPositions,
  ionStormGamePositionDeltaLy,
} from './futureTurnIonStorms'

describe('ionStormGamePositionDeltaLy', () => {
  it('moves north at heading 0 by warp squared per turn', () => {
    expect(ionStormGamePositionDeltaLy(0, 5, 1)).toEqual({ dx: 0, dy: 25 })
    expect(ionStormGamePositionDeltaLy(0, 5, 3)).toEqual({ dx: 0, dy: 75 })
  })

  it('moves east at heading 90', () => {
    const delta = ionStormGamePositionDeltaLy(90, 3, 1)
    expect(delta.dx).toBe(9)
    expect(delta.dy).toBeCloseTo(0)
  })
})

describe('applyFutureIonStormOverlayPositions', () => {
  it('shifts ion storm circles only', () => {
    const circles = [
      {
        layer: 'nebulae' as const,
        id: 'neb-1',
        x: 10,
        y: 20,
        radius: 50,
      },
      {
        layer: 'ion-storms' as const,
        id: 'is-1',
        x: 100,
        y: 200,
        radius: 30,
        class: 2,
        heading: 0,
        warp: 5,
      },
    ]
    const shifted = applyFutureIonStormOverlayPositions(circles, 2)
    expect(shifted[0]).toEqual(circles[0])
    expect(shifted[1]).toMatchObject({ x: 100, y: 250 })
  })
})
