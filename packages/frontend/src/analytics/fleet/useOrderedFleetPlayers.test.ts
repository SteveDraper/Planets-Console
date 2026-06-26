import { beforeEach, describe, expect, it } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useOrderedFleetPlayers } from './useOrderedFleetPlayers'
import { seedShellViewpoint } from './fleetTestShell'
import { useFleetPlayerVisibilityStore } from '../../stores/fleetPlayerVisibility'
import { useShellStore } from '../../stores/shell'

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
