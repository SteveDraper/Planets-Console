import { describe, expect, it } from 'vitest'
import { shownShellRefetchesForFleetAgeNotice } from './useHomeworldFleetAgeRefetch'

describe('shownShellRefetchesForFleetAgeNotice', () => {
  it('records the first sample without refetching', () => {
    expect(
      shownShellRefetchesForFleetAgeNotice({
        hasSampled: false,
        shellTurn: 8,
        fromTurn: 2,
      })
    ).toBe(false)
  })

  it('refetches a shown shell at or after the changed turn', () => {
    expect(
      shownShellRefetchesForFleetAgeNotice({
        hasSampled: true,
        shellTurn: 8,
        fromTurn: 8,
      })
    ).toBe(true)
    expect(
      shownShellRefetchesForFleetAgeNotice({
        hasSampled: true,
        shellTurn: 3,
        fromTurn: 8,
      })
    ).toBe(false)
  })

  it('does not refetch when the epoch has not moved', () => {
    expect(
      shownShellRefetchesForFleetAgeNotice({
        hasSampled: true,
        shellTurn: 8,
        fromTurn: null,
      })
    ).toBe(false)
  })
})
