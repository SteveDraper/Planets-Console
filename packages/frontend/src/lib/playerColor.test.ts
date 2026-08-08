import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { DiplomacyTier } from './diplomacyTier'
import {
  PLAYER_COLOR_PRESET,
  colorForPlayerId,
  defaultColorForPlayerId,
  diplomacyColorFamilyMemberIds,
  resetPlayerColorResolutionPort,
  setPlayerColorResolutionPort,
  tonalVariantForFamilyMember,
  type PlayerColorResolutionPort,
} from './playerColor'

function port(partial: Partial<PlayerColorResolutionPort>): PlayerColorResolutionPort {
  return {
    getMode: () => 'per_player',
    getOverride: () => undefined,
    getDiplomacyThreshold: () => DiplomacyTier.SAFE_PASSAGE,
    getFamilyBaseColor: () => '#34d399',
    getViewpointPlayerId: () => null,
    getInboundRelationFromByPlayerId: () => new Map(),
    ...partial,
  }
}

describe('playerColor', () => {
  beforeEach(() => {
    resetPlayerColorResolutionPort()
  })

  afterEach(() => {
    resetPlayerColorResolutionPort()
  })

  it('maps playerId % 16 into the preset table', () => {
    expect(defaultColorForPlayerId(0)).toBe(PLAYER_COLOR_PRESET[0])
    expect(defaultColorForPlayerId(1)).toBe(PLAYER_COLOR_PRESET[1])
    expect(defaultColorForPlayerId(15)).toBe(PLAYER_COLOR_PRESET[15])
    expect(defaultColorForPlayerId(16)).toBe(PLAYER_COLOR_PRESET[0])
    expect(defaultColorForPlayerId(-1)).toBe(PLAYER_COLOR_PRESET[15])
  })

  it('uses defaults when the resolution port is empty', () => {
    expect(colorForPlayerId(8)).toBe(defaultColorForPlayerId(8))
  })

  it('consults overrides in per-player mode', () => {
    setPlayerColorResolutionPort(
      port({
        getOverride: (playerId) => (playerId === 8 ? '#ffffff' : undefined),
      })
    )
    expect(colorForPlayerId(8)).toBe('#ffffff')
    expect(colorForPlayerId(9)).toBe(defaultColorForPlayerId(9))
  })

  it('lists diplomacy family members from inbound grants at or above threshold', () => {
    const inbound = new Map([
      [2, DiplomacyTier.SAFE_PASSAGE],
      [3, DiplomacyTier.AMBASSADOR],
      [4, DiplomacyTier.FULL_ALLIANCE],
    ])
    expect(
      diplomacyColorFamilyMemberIds(inbound, 1, DiplomacyTier.SAFE_PASSAGE)
    ).toEqual([2, 4])
  })

  it('paints family tones in diplomacy-family mode and defaults otherwise', () => {
    const inbound = new Map([
      [2, DiplomacyTier.SAFE_PASSAGE],
      [3, DiplomacyTier.NONE],
      [4, DiplomacyTier.SHARE_INTEL],
    ])
    setPlayerColorResolutionPort(
      port({
        getMode: () => 'diplomacy_family',
        getViewpointPlayerId: () => 1,
        getInboundRelationFromByPlayerId: () => inbound,
        getFamilyBaseColor: () => '#336699',
        getDiplomacyThreshold: () => DiplomacyTier.SAFE_PASSAGE,
      })
    )
    const family = [2, 4]
    expect(colorForPlayerId(2)).toBe(tonalVariantForFamilyMember('#336699', 2, family))
    expect(colorForPlayerId(4)).toBe(tonalVariantForFamilyMember('#336699', 4, family))
    expect(colorForPlayerId(3)).toBe(defaultColorForPlayerId(3))
    expect(colorForPlayerId(1)).toBe(defaultColorForPlayerId(1))
  })

  it('treats missing inbound relation as not in family', () => {
    setPlayerColorResolutionPort(
      port({
        getMode: () => 'diplomacy_family',
        getViewpointPlayerId: () => 1,
        getInboundRelationFromByPlayerId: () => new Map([[2, DiplomacyTier.SAFE_PASSAGE]]),
      })
    )
    expect(colorForPlayerId(9)).toBe(defaultColorForPlayerId(9))
  })

  it('produces stable tonal variants for the same family inputs', () => {
    const a = tonalVariantForFamilyMember('#34d399', 2, [2, 5, 9])
    const b = tonalVariantForFamilyMember('#34d399', 2, [9, 2, 5])
    expect(a).toBe(b)
    expect(a).toMatch(/^#[0-9a-f]{6}$/)
    expect(tonalVariantForFamilyMember('#34d399', 5, [2, 5, 9])).not.toBe(a)
  })
})
