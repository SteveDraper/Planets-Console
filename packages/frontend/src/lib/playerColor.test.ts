import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { DiplomacyTier } from './diplomacyTier'
import {
  PLAYER_COLOR_PRESET,
  colorForPlayerId,
  defaultColorForPlayerId,
  diplomacyColorFamilyMemberIds,
  outOfCircleFamilyMemberIds,
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
    getOutOfCircleBaseColor: () => '#f43f5e',
    getViewpointPlayerId: () => null,
    getInboundRelationFromByPlayerId: () => new Map(),
    getRosterPlayerIds: () => [],
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

  it('lists diplomacy family members including viewpoint plus inbound grants at threshold', () => {
    const inbound = new Map([
      [2, DiplomacyTier.SAFE_PASSAGE],
      [3, DiplomacyTier.AMBASSADOR],
      [4, DiplomacyTier.FULL_ALLIANCE],
    ])
    expect(
      diplomacyColorFamilyMemberIds(inbound, 1, DiplomacyTier.SAFE_PASSAGE)
    ).toEqual([1, 2, 4])
    expect(outOfCircleFamilyMemberIds([1, 2, 3, 4, 5], [1, 2, 4])).toEqual([3, 5])
  })

  it('paints two family bases in diplomacy-family mode with viewpoint brightest in-circle', () => {
    const inbound = new Map([
      [2, DiplomacyTier.SAFE_PASSAGE],
      [3, DiplomacyTier.NONE],
      [4, DiplomacyTier.SHARE_INTEL],
    ])
    const roster = [1, 2, 3, 4]
    setPlayerColorResolutionPort(
      port({
        getMode: () => 'diplomacy_family',
        getViewpointPlayerId: () => 1,
        getInboundRelationFromByPlayerId: () => inbound,
        getFamilyBaseColor: () => '#336699',
        getOutOfCircleBaseColor: () => '#aa3333',
        getDiplomacyThreshold: () => DiplomacyTier.SAFE_PASSAGE,
        getRosterPlayerIds: () => roster,
      })
    )
    const inCircle = [1, 2, 4]
    const outCircle = [3]
    expect(colorForPlayerId(1)).toBe(
      tonalVariantForFamilyMember('#336699', 1, inCircle, 1)
    )
    expect(colorForPlayerId(2)).toBe(
      tonalVariantForFamilyMember('#336699', 2, inCircle, 1)
    )
    expect(colorForPlayerId(4)).toBe(
      tonalVariantForFamilyMember('#336699', 4, inCircle, 1)
    )
    expect(colorForPlayerId(3)).toBe(
      tonalVariantForFamilyMember('#aa3333', 3, outCircle, null)
    )
    expect(colorForPlayerId(3)).not.toBe(defaultColorForPlayerId(3))
    const viewpointRgb = hexLightness(colorForPlayerId(1))
    expect(viewpointRgb).toBeGreaterThan(hexLightness(colorForPlayerId(2)))
    expect(viewpointRgb).toBeGreaterThan(hexLightness(colorForPlayerId(4)))
  })

  it('paints missing-relation roster players with the out-of-circle base', () => {
    setPlayerColorResolutionPort(
      port({
        getMode: () => 'diplomacy_family',
        getViewpointPlayerId: () => 1,
        getInboundRelationFromByPlayerId: () => new Map([[2, DiplomacyTier.SAFE_PASSAGE]]),
        getOutOfCircleBaseColor: () => '#aa3333',
        getRosterPlayerIds: () => [1, 2, 9],
      })
    )
    expect(colorForPlayerId(9)).toBe(
      tonalVariantForFamilyMember('#aa3333', 9, [9], null)
    )
  })

  it('produces stable tonal variants for the same family inputs', () => {
    const a = tonalVariantForFamilyMember('#34d399', 2, [1, 2, 5, 9], 1)
    const b = tonalVariantForFamilyMember('#34d399', 2, [9, 1, 2, 5], 1)
    expect(a).toBe(b)
    expect(a).toMatch(/^#[0-9a-f]{6}$/)
    expect(tonalVariantForFamilyMember('#34d399', 5, [1, 2, 5, 9], 1)).not.toBe(a)
    expect(hexLightness(tonalVariantForFamilyMember('#34d399', 1, [1, 2, 5], 1))).toBeGreaterThan(
      hexLightness(tonalVariantForFamilyMember('#34d399', 2, [1, 2, 5], 1))
    )
  })
})

function hexLightness(hex: string): number {
  const raw = hex.startsWith('#') ? hex.slice(1) : hex
  const r = parseInt(raw.slice(0, 2), 16) / 255
  const g = parseInt(raw.slice(2, 4), 16) / 255
  const b = parseInt(raw.slice(4, 6), 16) / 255
  return (Math.max(r, g, b) + Math.min(r, g, b)) / 2
}
