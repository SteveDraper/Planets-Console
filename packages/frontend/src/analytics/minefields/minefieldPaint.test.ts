import { describe, expect, it } from 'vitest'
import { DiplomacyTier } from '../../lib/diplomacyTier'
import {
  PLAYER_COLOR_PRESET,
  buildPlayerColorPaintSnapshot,
  defaultPlayerColorPaintSnapshotInputs,
} from '../../lib/playerColor'
import {
  defaultMinefieldTypePreferences,
  isMinefieldStanceInCircle,
  minefieldOwnerColor,
  resolveMinefieldPaintColor,
} from './minefieldPaint'

describe('minefield paint colors', () => {
  it('owner policy uses per-player palette and ignores global diplomacy mode', () => {
    const snapshot = buildPlayerColorPaintSnapshot({
      ...defaultPlayerColorPaintSnapshotInputs(),
      mode: 'diplomacy_family',
      viewpointPlayerId: 1,
      inboundRelationFromByPlayerId: new Map([[2, DiplomacyTier.FULL_ALLIANCE]]),
      rosterPlayerIds: [1, 2, 3],
    })
    const prefs = defaultMinefieldTypePreferences().normal
    expect(prefs.policy).toBe('owner')
    expect(
      resolveMinefieldPaintColor({
        isWeb: false,
        ownerId: 3,
        preferences: prefs,
        paintSnapshot: snapshot,
        viewpointPlayerId: 1,
        inboundRelationFromByPlayerId: snapshot.inCircleMemberIds
          ? new Map([[2, DiplomacyTier.FULL_ALLIANCE]])
          : new Map(),
      })
    ).toBe(PLAYER_COLOR_PRESET[3 % PLAYER_COLOR_PRESET.length])
    expect(minefieldOwnerColor(3, snapshot)).toBe(PLAYER_COLOR_PRESET[3 % 16])
  })

  it('owner policy honors per-player overrides', () => {
    const snapshot = buildPlayerColorPaintSnapshot({
      ...defaultPlayerColorPaintSnapshotInputs(),
      mode: 'diplomacy_family',
      overrides: { '3': '#112233' },
    })
    expect(minefieldOwnerColor(3, snapshot)).toBe('#112233')
  })

  it('stance buckets viewpoint and Safe Passage inbound as in-circle', () => {
    const inbound = new Map([
      [2, DiplomacyTier.SAFE_PASSAGE],
      [3, DiplomacyTier.AMBASSADOR],
    ])
    expect(isMinefieldStanceInCircle(1, 1, inbound)).toBe(true)
    expect(isMinefieldStanceInCircle(2, 1, inbound)).toBe(true)
    expect(isMinefieldStanceInCircle(3, 1, inbound)).toBe(false)
    expect(isMinefieldStanceInCircle(4, 1, inbound)).toBe(false)
  })

  it('web defaults to stance purple pair', () => {
    const prefs = defaultMinefieldTypePreferences().web
    expect(prefs.policy).toBe('stance')
    const snapshot = buildPlayerColorPaintSnapshot(defaultPlayerColorPaintSnapshotInputs())
    const inbound = new Map([[2, DiplomacyTier.SAFE_PASSAGE]])
    expect(
      resolveMinefieldPaintColor({
        isWeb: true,
        ownerId: 1,
        preferences: prefs,
        paintSnapshot: snapshot,
        viewpointPlayerId: 1,
        inboundRelationFromByPlayerId: inbound,
      })
    ).toBe('#8480d4')
    expect(
      resolveMinefieldPaintColor({
        isWeb: true,
        ownerId: 3,
        preferences: prefs,
        paintSnapshot: snapshot,
        viewpointPlayerId: 1,
        inboundRelationFromByPlayerId: inbound,
      })
    ).toBe('#a78bfa')
  })

  it('normal stance defaults to green/rose pair', () => {
    const prefs = {
      ...defaultMinefieldTypePreferences().normal,
      policy: 'stance' as const,
    }
    const snapshot = buildPlayerColorPaintSnapshot(defaultPlayerColorPaintSnapshotInputs())
    expect(
      resolveMinefieldPaintColor({
        isWeb: false,
        ownerId: 1,
        preferences: prefs,
        paintSnapshot: snapshot,
        viewpointPlayerId: 1,
        inboundRelationFromByPlayerId: new Map(),
      })
    ).toBe('#34d399')
    expect(
      resolveMinefieldPaintColor({
        isWeb: false,
        ownerId: 9,
        preferences: prefs,
        paintSnapshot: snapshot,
        viewpointPlayerId: 1,
        inboundRelationFromByPlayerId: new Map(),
      })
    ).toBe('#fb7185')
  })
})
