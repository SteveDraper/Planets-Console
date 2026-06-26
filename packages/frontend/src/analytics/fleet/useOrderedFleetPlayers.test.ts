import { beforeEach, describe, expect, it } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useOrderedFleetPlayers } from './useOrderedFleetPlayers'
import { useFleetPlayerVisibilityStore } from '../../stores/fleetPlayerVisibility'
import { useShellStore } from '../../stores/shell'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../stellar-cartography/layers'

const players = [
  { ordinal: 1, playerId: 8, name: 'Alice', raceName: null },
  { ordinal: 2, playerId: 9, name: 'Bob', raceName: null },
] as const

function seedShellViewpoint(viewpointName: 'Alice' | 'Bob') {
  useShellStore.setState({
    selectedGameId: '628580',
    gameInfoContext: {
      turn: 10,
      perspectives: [...players],
      isGameFinished: true,
      sectorDisplayName: 'Test Sector',
      stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
    },
    selectedTurn: 5,
    perspectiveOverrideName: viewpointName,
    storageOnlyLoad: false,
    storageAvailablePerspectives: null,
  })
}

describe('useOrderedFleetPlayers', () => {
  beforeEach(() => {
    useFleetPlayerVisibilityStore.setState({ overrides: {} })
    useShellStore.setState({
      selectedGameId: null,
      gameInfoContext: null,
      selectedTurn: null,
      perspectiveOverrideName: null,
      storageOnlyLoad: false,
      storageAvailablePerspectives: null,
    })
  })

  it('orders players with the viewpoint first', () => {
    seedShellViewpoint('Bob')

    const { result } = renderHook(() => useOrderedFleetPlayers())

    expect(result.current.players.map((player) => player.name)).toEqual(['Bob', 'Alice'])
    expect(result.current.viewpointPlayerId).toBe(9)
  })

  it('returns all ordered players by default', () => {
    seedShellViewpoint('Alice')
    useFleetPlayerVisibilityStore.getState().setFleetPlayerVisible(9, false)

    const { result } = renderHook(() => useOrderedFleetPlayers())

    expect(result.current.players.map((player) => player.playerId)).toEqual([8, 9])
    expect(result.current.isPlayerVisible(9)).toBe(false)
  })

  it('filters to visible players when visibleOnly is true', () => {
    seedShellViewpoint('Alice')
    useFleetPlayerVisibilityStore.getState().setFleetPlayerVisible(9, false)

    const { result } = renderHook(() => useOrderedFleetPlayers({ visibleOnly: true }))

    expect(result.current.players.map((player) => player.name)).toEqual(['Alice'])
  })

  it('keeps viewpoint ordering when filtering visible players', () => {
    seedShellViewpoint('Bob')
    useFleetPlayerVisibilityStore.getState().setFleetPlayerVisible(8, false)

    const { result } = renderHook(() => useOrderedFleetPlayers({ visibleOnly: true }))

    expect(result.current.players.map((player) => player.name)).toEqual(['Bob'])
  })
})
