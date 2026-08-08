import { renderHook, act } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { DiplomacyTier } from '../lib/diplomacyTier'
import {
  colorForPlayerId,
  defaultColorForPlayerId,
  resetPlayerColorResolutionPort,
  tonalVariantForFamilyMember,
} from '../lib/playerColor'
import {
  clearPlayerColorPaintContext,
  installPlayerColorsStorePort,
  PLAYER_COLORS_STORAGE_KEY,
  resetPlayerColorsStoreState,
  usePlayerColor,
  usePlayerColorsStore,
} from './playerColors'

describe('usePlayerColorsStore', () => {
  beforeEach(() => {
    localStorage.removeItem(PLAYER_COLORS_STORAGE_KEY)
    resetPlayerColorsStoreState()
    resetPlayerColorResolutionPort()
    installPlayerColorsStorePort()
  })

  it('starts with empty overrides and returns preset defaults', () => {
    expect(usePlayerColorsStore.getState().overrides).toEqual({})
    expect(colorForPlayerId(3)).toBe(defaultColorForPlayerId(3))
  })

  it('setPlayerColorOverride updates the snapshot used by colorForPlayerId', () => {
    usePlayerColorsStore.getState().setPlayerColorOverride(3, '#112233')
    expect(colorForPlayerId(3)).toBe('#112233')

    usePlayerColorsStore.getState().setPlayerColorOverride(3, null)
    expect(colorForPlayerId(3)).toBe(defaultColorForPlayerId(3))
  })

  it('preserves overrides when switching to diplomacy-family mode', () => {
    usePlayerColorsStore.getState().setPlayerColorOverride(3, '#112233')
    usePlayerColorsStore.getState().setPlayerColorMode('diplomacy_family')
    expect(usePlayerColorsStore.getState().overrides['3']).toBe('#112233')
    expect(colorForPlayerId(3)).toBe(defaultColorForPlayerId(3))
    usePlayerColorsStore.getState().setPlayerColorMode('per_player')
    expect(colorForPlayerId(3)).toBe('#112233')
  })

  it('usePlayerColor re-renders when the player override changes', () => {
    const { result } = renderHook(() => usePlayerColor(3))
    expect(result.current).toBe(defaultColorForPlayerId(3))

    act(() => {
      usePlayerColorsStore.getState().setPlayerColorOverride(3, '#abcdef')
    })
    expect(result.current).toBe('#abcdef')

    act(() => {
      usePlayerColorsStore.getState().setPlayerColorOverride(3, null)
    })
    expect(result.current).toBe(defaultColorForPlayerId(3))
  })

  it('usePlayerColor re-renders when diplomacy paint context changes', () => {
    const { result } = renderHook(() => usePlayerColor(2))
    act(() => {
      usePlayerColorsStore.getState().setPlayerColorMode('diplomacy_family')
      usePlayerColorsStore.getState().setFamilyBaseColor('#336699')
      usePlayerColorsStore.getState().setPaintContext({
        viewpointPlayerId: 1,
        inboundRelationFromByPlayerId: new Map([[2, DiplomacyTier.SAFE_PASSAGE]]),
        rosterPlayerIds: [1, 2, 3],
      })
    })
    expect(result.current).toBe(tonalVariantForFamilyMember('#336699', 2, [1, 2], 1))
  })

  it('setPaintContext is a no-op when viewpoint, inbound map, and roster are unchanged', () => {
    usePlayerColorsStore.getState().setPaintContext({
      viewpointPlayerId: 1,
      inboundRelationFromByPlayerId: new Map([[2, DiplomacyTier.SAFE_PASSAGE]]),
      rosterPlayerIds: [1, 2, 3],
    })
    const snapshotBefore = usePlayerColorsStore.getState().paintSnapshot

    usePlayerColorsStore.getState().setPaintContext({
      viewpointPlayerId: 1,
      inboundRelationFromByPlayerId: new Map([[2, DiplomacyTier.SAFE_PASSAGE]]),
      rosterPlayerIds: [1, 2, 3],
    })
    expect(usePlayerColorsStore.getState().paintSnapshot).toBe(snapshotBefore)

    usePlayerColorsStore.getState().setPaintContext({
      viewpointPlayerId: 1,
      inboundRelationFromByPlayerId: new Map([[2, DiplomacyTier.FULL_ALLIANCE]]),
      rosterPlayerIds: [1, 2, 3],
    })
    expect(usePlayerColorsStore.getState().paintSnapshot).not.toBe(snapshotBefore)
  })

  it('persists mode, threshold, bases, and overrides to localStorage', () => {
    usePlayerColorsStore.getState().setPlayerColorOverride(3, '#112233')
    usePlayerColorsStore.getState().setPlayerColorMode('diplomacy_family')
    usePlayerColorsStore.getState().setDiplomacyThreshold(DiplomacyTier.SHARE_INTEL)
    usePlayerColorsStore.getState().setFamilyBaseColor('#336699')
    usePlayerColorsStore.getState().setOutOfCircleBaseColor('#aa3333')
    usePlayerColorsStore.getState().setPaintContext({
      viewpointPlayerId: 1,
      inboundRelationFromByPlayerId: new Map([[2, DiplomacyTier.SAFE_PASSAGE]]),
      rosterPlayerIds: [1, 2],
    })

    const raw = localStorage.getItem(PLAYER_COLORS_STORAGE_KEY)
    expect(raw).toBeTruthy()
    expect(raw).toContain('"mode":"diplomacy_family"')
    expect(raw).toContain('"diplomacyThreshold":3')
    expect(raw).toContain('"familyBaseColor":"#336699"')
    expect(raw).toContain('"outOfCircleBaseColor":"#aa3333"')
    expect(raw).toContain('"3":"#112233"')
    expect(raw).not.toContain('viewpointPlayerId')
    expect(raw).not.toContain('inboundRelationFromByPlayerId')
    expect(raw).not.toContain('rosterPlayerIds')
    expect(raw).not.toContain('paintSnapshot')
  })

  it('rehydrates persisted knobs and rebuilds the paint snapshot', async () => {
    localStorage.setItem(
      PLAYER_COLORS_STORAGE_KEY,
      JSON.stringify({
        state: {
          overrides: { '3': '#112233' },
          mode: 'diplomacy_family',
          diplomacyThreshold: DiplomacyTier.SHARE_INTEL,
          familyBaseColor: '#336699',
          outOfCircleBaseColor: '#aa3333',
        },
        version: 0,
      })
    )

    await usePlayerColorsStore.persist.rehydrate()

    const state = usePlayerColorsStore.getState()
    expect(state.mode).toBe('diplomacy_family')
    expect(state.diplomacyThreshold).toBe(DiplomacyTier.SHARE_INTEL)
    expect(state.familyBaseColor).toBe('#336699')
    expect(state.outOfCircleBaseColor).toBe('#aa3333')
    expect(state.overrides['3']).toBe('#112233')
    expect(state.viewpointPlayerId).toBeNull()
    expect(state.rosterPlayerIds).toEqual([])
    expect(state.paintSnapshot.mode).toBe('diplomacy_family')
    expect(state.paintSnapshot.familyBaseColor).toBe('#336699')
    expect(state.paintSnapshot.overrides['3']).toBe('#112233')
  })

  it('ignores invalid persisted mode and threshold on rehydrate', async () => {
    usePlayerColorsStore.getState().setPlayerColorMode('diplomacy_family')
    usePlayerColorsStore.getState().setDiplomacyThreshold(DiplomacyTier.FULL_ALLIANCE)
    usePlayerColorsStore.getState().setFamilyBaseColor('#abcdef')

    localStorage.setItem(
      PLAYER_COLORS_STORAGE_KEY,
      JSON.stringify({
        state: {
          overrides: { '1': '#000001' },
          mode: 'not_a_mode',
          diplomacyThreshold: -1,
          familyBaseColor: '',
          outOfCircleBaseColor: '#aa3333',
        },
        version: 0,
      })
    )

    await usePlayerColorsStore.persist.rehydrate()

    const state = usePlayerColorsStore.getState()
    expect(state.mode).toBe('diplomacy_family')
    expect(state.diplomacyThreshold).toBe(DiplomacyTier.FULL_ALLIANCE)
    expect(state.familyBaseColor).toBe('#abcdef')
    expect(state.outOfCircleBaseColor).toBe('#aa3333')
    expect(state.overrides['1']).toBe('#000001')
  })

  it('clearPlayerColorPaintContext is a no-op when already cleared', () => {
    const snapshotBefore = usePlayerColorsStore.getState().paintSnapshot
    clearPlayerColorPaintContext()
    expect(usePlayerColorsStore.getState().paintSnapshot).toBe(snapshotBefore)

    usePlayerColorsStore.getState().setPaintContext({
      viewpointPlayerId: 1,
      inboundRelationFromByPlayerId: new Map([[2, DiplomacyTier.SAFE_PASSAGE]]),
      rosterPlayerIds: [1, 2],
    })
    const painted = usePlayerColorsStore.getState().paintSnapshot
    expect(painted).not.toBe(snapshotBefore)

    clearPlayerColorPaintContext()
    const cleared = usePlayerColorsStore.getState().paintSnapshot
    expect(cleared).not.toBe(painted)

    clearPlayerColorPaintContext()
    expect(usePlayerColorsStore.getState().paintSnapshot).toBe(cleared)
  })
})
