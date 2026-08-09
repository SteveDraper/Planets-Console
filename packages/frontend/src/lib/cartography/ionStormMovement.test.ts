import { describe, expect, it } from 'vitest'
import { headingTravelDeltaGameLy, ionStormStepDeltaGameLy } from './ionStormMovement'

describe('ionStormStepDeltaGameLy', () => {
  it('moves north at heading 0 by warp squared per turn', () => {
    expect(ionStormStepDeltaGameLy(0, 5)).toEqual({ dx: 0, dy: 25 })
  })

  it('moves east at heading 90', () => {
    const delta = ionStormStepDeltaGameLy(90, 3)
    expect(delta.dx).toBe(9)
    expect(delta.dy).toBeCloseTo(0)
  })

  it('treats undefined warp as zero movement', () => {
    expect(ionStormStepDeltaGameLy(45, undefined)).toEqual({ dx: 0, dy: 0 })
  })
})

describe('headingTravelDeltaGameLy', () => {
  it('scales an arbitrary ly length along heading', () => {
    expect(headingTravelDeltaGameLy(0, 81)).toEqual({ dx: 0, dy: 81 })
    const east = headingTravelDeltaGameLy(90, 16)
    expect(east.dx).toBeCloseTo(16)
    expect(east.dy).toBeCloseTo(0)
  })
})
