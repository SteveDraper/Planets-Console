import { beforeEach, describe, expect, it } from 'vitest'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../analytics/stellar-cartography/layers'
import { perspectiveRow } from '../lib/perspectiveRowTestFixtures'
import {
  SHELL_STORAGE_KEY,
  useShellStore,
  type GameInfoShellContext,
} from '../stores/shell'

function unfinishedCtx(turn: number): GameInfoShellContext {
  return {
    turn,
    perspectives: [perspectiveRow(1, 'Alice')],
    isGameFinished: false,
    sectorDisplayName: null,
    stellarCartographyGates: EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
  }
}

describe('useShellStore', () => {
  beforeEach(() => {
    localStorage.removeItem(SHELL_STORAGE_KEY)
    useShellStore.setState({
      selectedGameId: null,
      gameInfoContext: null,
      selectedTurn: null,
      perspectiveOverrideOrdinal: null,
      lastShellGameId: null,
      storageOnlyLoad: false,
      storageAvailablePerspectives: null,
      viewMode: 'map',
    })
  })

  it('defaults shell fields before persistence', () => {
    expect(useShellStore.getState().selectedGameId).toBeNull()
    expect(useShellStore.getState().selectedTurn).toBeNull()
    expect(useShellStore.getState().perspectiveOverrideOrdinal).toBeNull()
    expect(useShellStore.getState().viewMode).toBe('map')
  })

  it('persists selected game, turn, viewpoint, and view mode to localStorage', () => {
    useShellStore.getState().setViewMode('tabular')
    useShellStore.setState({
      selectedGameId: '628580',
      selectedTurn: 42,
      perspectiveOverrideOrdinal: 2,
      lastShellGameId: '628580',
    })

    const raw = localStorage.getItem(SHELL_STORAGE_KEY)
    expect(raw).toBeTruthy()
    expect(raw).toContain('628580')
    expect(raw).toContain('42')
    expect(raw).toContain('"perspectiveOverrideOrdinal":2')
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

  describe('applyGameInfoRefresh', () => {
    it('does not auto-advance selected turn on same-game refresh when still in range', () => {
      useShellStore.setState({
        selectedGameId: '99',
        lastShellGameId: '99',
        selectedTurn: 5,
        gameInfoContext: unfinishedCtx(5),
      })

      useShellStore.getState().applyGameInfoRefresh('99', unfinishedCtx(8), {
        selectableTurnMax: 8,
      })

      const state = useShellStore.getState()
      expect(state.selectedTurn).toBe(5)
      expect(state.gameInfoContext?.turn).toBe(8)
    })

    it('jumps selected turn to turn cap when switching games', () => {
      useShellStore.setState({
        selectedGameId: '10',
        lastShellGameId: '10',
        selectedTurn: 3,
        gameInfoContext: unfinishedCtx(5),
      })

      useShellStore.getState().applyGameInfoRefresh('99', unfinishedCtx(8), {
        selectableTurnMax: 8,
      })

      expect(useShellStore.getState().selectedTurn).toBe(8)
      expect(useShellStore.getState().selectedGameId).toBe('99')
    })
  })
})
