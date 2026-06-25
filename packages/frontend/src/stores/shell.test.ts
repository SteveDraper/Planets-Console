import { beforeEach, describe, expect, it } from 'vitest'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../analytics/stellar-cartography/layers'
import { perspectiveRow } from '../lib/perspectiveRowTestFixtures'
import { SHELL_STORAGE_KEY, useShellStore } from '../stores/shell'

describe('useShellStore', () => {
  beforeEach(() => {
    localStorage.removeItem(SHELL_STORAGE_KEY)
    useShellStore.setState({
      selectedGameId: null,
      gameInfoContext: null,
      selectedTurn: null,
      perspectiveOverrideName: null,
      lastShellGameId: null,
      storageOnlyLoad: false,
      storageAvailablePerspectives: null,
      viewMode: 'map',
    })
  })

  it('defaults shell fields before persistence', () => {
    expect(useShellStore.getState().selectedGameId).toBeNull()
    expect(useShellStore.getState().selectedTurn).toBeNull()
    expect(useShellStore.getState().perspectiveOverrideName).toBeNull()
    expect(useShellStore.getState().viewMode).toBe('map')
  })

  it('persists selected game, turn, viewpoint, and view mode to localStorage', () => {
    useShellStore.getState().setViewMode('tabular')
    useShellStore.setState({
      selectedGameId: '628580',
      selectedTurn: 42,
      perspectiveOverrideName: 'Player Two',
      lastShellGameId: '628580',
    })

    const raw = localStorage.getItem(SHELL_STORAGE_KEY)
    expect(raw).toBeTruthy()
    expect(raw).toContain('628580')
    expect(raw).toContain('42')
    expect(raw).toContain('Player Two')
    expect(raw).toContain('tabular')
  })

  it('does not persist game info context', () => {
    useShellStore.setState({
      selectedGameId: '628580',
      gameInfoContext: {
        turn: 10,
        perspectives: [perspectiveRow(1, 'A', { raceName: 'Federation' })],
        isGameFinished: false,
        sectorDisplayName: 'Test Sector',
        stellarCartographyGates: EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
      },
    })

    const raw = localStorage.getItem(SHELL_STORAGE_KEY)
    expect(raw).toBeTruthy()
    expect(raw).not.toContain('Test Sector')
    expect(raw).not.toContain('Federation')
  })
})
