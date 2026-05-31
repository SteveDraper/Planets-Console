import { describe, expect, it } from 'vitest'
import { ionStormStepDeltaGameLy } from './ionStormMovement'

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
