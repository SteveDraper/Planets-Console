import { describe, expect, it } from 'vitest'
import { headingTravelDeltaGameLy } from './headingTravel'

describe('headingTravelDeltaGameLy', () => {
  it('scales an arbitrary ly length along heading', () => {
    expect(headingTravelDeltaGameLy(0, 81)).toEqual({ dx: 0, dy: 81 })
    const east = headingTravelDeltaGameLy(90, 16)
    expect(east.dx).toBeCloseTo(16)
    expect(east.dy).toBeCloseTo(0)
  })
})
