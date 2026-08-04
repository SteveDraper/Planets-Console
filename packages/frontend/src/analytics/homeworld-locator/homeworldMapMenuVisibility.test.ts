import { describe, expect, it } from 'vitest'
import {
  isPlanetLocationAsserted,
  locationAssertMenuActions,
} from './homeworldMapMenuVisibility'

describe('isPlanetLocationAsserted', () => {
  it('returns false when the planet has no marker', () => {
    expect(isPlanetLocationAsserted([], 9)).toBe(false)
  })

  it('returns false when locationAsserted is omitted or false', () => {
    expect(
      isPlanetLocationAsserted([{ planetId: 9, locationAsserted: false }], 9)
    ).toBe(false)
  })

  it('returns true only for the matching planet with locationAsserted', () => {
    expect(
      isPlanetLocationAsserted(
        [
          { planetId: 1, locationAsserted: false },
          { planetId: 9, locationAsserted: true },
        ],
        9
      )
    ).toBe(true)
    expect(
      isPlanetLocationAsserted([{ planetId: 9, locationAsserted: true }], 1)
    ).toBe(false)
  })
})

describe('locationAssertMenuActions', () => {
  it('shows Assert only when location is not asserted', () => {
    expect(locationAssertMenuActions(false)).toEqual({
      showAssertAsHomeworld: true,
      showRevokeHomeworldAssert: false,
    })
  })

  it('shows Revoke only when location is asserted', () => {
    expect(locationAssertMenuActions(true)).toEqual({
      showAssertAsHomeworld: false,
      showRevokeHomeworldAssert: true,
    })
  })
})
