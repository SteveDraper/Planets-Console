import { beforeEach, describe, expect, it } from 'vitest'
import {
  colorForPlayerId,
  defaultColorForPlayerId,
  resetPlayerColorOverrideStore,
} from '../lib/playerColor'
import { installPlayerColorsStorePort, usePlayerColorsStore } from './playerColors'

describe('usePlayerColorsStore', () => {
  beforeEach(() => {
    usePlayerColorsStore.setState({ overrides: {} })
    resetPlayerColorOverrideStore()
    installPlayerColorsStorePort()
  })

  it('starts with empty overrides and returns preset defaults', () => {
    expect(usePlayerColorsStore.getState().overrides).toEqual({})
    expect(usePlayerColorsStore.getState().colorForPlayerId(3)).toBe(
      defaultColorForPlayerId(3)
    )
    expect(colorForPlayerId(3)).toBe(defaultColorForPlayerId(3))
  })

  it('setPlayerColorOverride updates the storage port used by colorForPlayerId', () => {
    usePlayerColorsStore.getState().setPlayerColorOverride(3, '#112233')
    expect(colorForPlayerId(3)).toBe('#112233')
    expect(usePlayerColorsStore.getState().colorForPlayerId(3)).toBe('#112233')

    usePlayerColorsStore.getState().setPlayerColorOverride(3, null)
    expect(colorForPlayerId(3)).toBe(defaultColorForPlayerId(3))
  })
})
