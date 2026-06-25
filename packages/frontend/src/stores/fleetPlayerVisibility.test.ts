import { beforeEach, describe, expect, it } from 'vitest'
import {
  FLEET_PLAYER_VISIBILITY_STORAGE_KEY,
  useFleetPlayerVisibilityStore,
} from './fleetPlayerVisibility'

describe('useFleetPlayerVisibilityStore', () => {
  beforeEach(() => {
    localStorage.removeItem(FLEET_PLAYER_VISIBILITY_STORAGE_KEY)
    useFleetPlayerVisibilityStore.setState({ overrides: {} })
  })

  it('defaults to all players visible', () => {
    const { isFleetPlayerVisible } = useFleetPlayerVisibilityStore.getState()
    expect(isFleetPlayerVisible(8, 8)).toBe(true)
    expect(isFleetPlayerVisible(9, 8)).toBe(true)
  })

  it('persists per-player overrides to localStorage', () => {
    useFleetPlayerVisibilityStore.getState().setFleetPlayerVisible(9, true)
    const raw = localStorage.getItem(FLEET_PLAYER_VISIBILITY_STORAGE_KEY)
    expect(raw).toBeTruthy()
    expect(raw).toContain('"9":true')
  })

  it('reads persisted overrides after rehydrate-style state', () => {
    useFleetPlayerVisibilityStore.setState({ overrides: { '9': true, '8': false } })
    const { isFleetPlayerVisible } = useFleetPlayerVisibilityStore.getState()
    expect(isFleetPlayerVisible(9, 8)).toBe(true)
    expect(isFleetPlayerVisible(8, 8)).toBe(false)
  })
})
