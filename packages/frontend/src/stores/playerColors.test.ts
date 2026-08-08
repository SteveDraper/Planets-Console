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
  installPlayerColorsStorePort,
  resetPlayerColorsStoreState,
  usePlayerColor,
  usePlayerColorsStore,
} from './playerColors'

describe('usePlayerColorsStore', () => {
  beforeEach(() => {
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
})
