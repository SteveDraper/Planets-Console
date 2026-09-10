import { describe, expect, it } from 'vitest'
import { foldAvailableEnabledAnalyticIds } from '../shellAnalyticRegistry'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../stellar-cartography/layers'
import { MINEFIELDS_ANALYTIC_ID } from '../mapAnalyticIds'
import {
  INACTIVE_REASON_NO_MINEFIELDS,
  MINEFIELDS_INACTIVE_HINT,
  minefieldsInactiveHint,
  minefieldsInactiveReasonFromGameInfo,
} from './minefieldsAvailability'

describe('minefieldsInactiveReasonFromGameInfo', () => {
  it('returns null when minefields exist', () => {
    expect(
      minefieldsInactiveReasonFromGameInfo({
        game: { id: 1 },
        settings: { nominefields: false },
      })
    ).toBeNull()
  })

  it('detects nominefields from settings', () => {
    expect(
      minefieldsInactiveReasonFromGameInfo({
        game: { id: 1 },
        settings: { nominefields: true },
      })
    ).toBe(INACTIVE_REASON_NO_MINEFIELDS)
  })

  it('detects nominefields from the game block', () => {
    expect(
      minefieldsInactiveReasonFromGameInfo({
        game: { id: 1, nominefields: true },
        settings: {},
      })
    ).toBe(INACTIVE_REASON_NO_MINEFIELDS)
  })
})

describe('minefieldsInactiveHint', () => {
  it('uses the locked product copy', () => {
    expect(minefieldsInactiveHint(INACTIVE_REASON_NO_MINEFIELDS)).toBe(MINEFIELDS_INACTIVE_HINT)
  })
})

describe('foldAvailableEnabledAnalyticIds (minefields availability)', () => {
  it('keeps minefields when available', () => {
    expect(
      foldAvailableEnabledAnalyticIds(['scores', MINEFIELDS_ANALYTIC_ID], {
        turn: 1,
        perspectives: [],
        isGameFinished: true,
        sectorDisplayName: null,
        stellarCartographyGates: EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
        homeworldInactiveReason: null,
        minefieldsInactiveReason: null,
      })
    ).toEqual(['scores', MINEFIELDS_ANALYTIC_ID])
  })

  it('drops minefields from effective enabled ids when nominefields', () => {
    expect(
      foldAvailableEnabledAnalyticIds(['scores', MINEFIELDS_ANALYTIC_ID], {
        turn: 1,
        perspectives: [],
        isGameFinished: true,
        sectorDisplayName: null,
        stellarCartographyGates: EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
        homeworldInactiveReason: null,
        minefieldsInactiveReason: INACTIVE_REASON_NO_MINEFIELDS,
      })
    ).toEqual(['scores'])
  })
})
