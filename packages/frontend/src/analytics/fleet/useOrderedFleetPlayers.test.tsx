import { beforeEach, describe, expect, it } from 'vitest'
import { renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useOrderedFleetPlayers } from './useOrderedFleetPlayers'
import { seedShellViewpoint } from './fleetTestShell'
import { useFleetPlayerVisibilityStore } from '../../stores/fleetPlayerVisibility'
import { useShellStore } from '../../stores/shell'

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('useOrderedFleetPlayers', () => {
  beforeEach(() => {
    useFleetPlayerVisibilityStore.setState({ overrides: {} })
    useShellStore.setState({
      selectedGameId: null,
      gameInfoContext: null,
      selectedTurn: null,
      perspectiveOverrideOrdinal: null,
      storageOnlyLoad: false,
      storageAvailablePerspectives: null,
    })
  })

  it('orders players with the viewpoint first', () => {
    seedShellViewpoint(2)

    const { result } = renderHook(() => useOrderedFleetPlayers(), {
      wrapper: createWrapper(),
    })

    expect(result.current.players.map((player) => player.name)).toEqual(['Bob', 'Alice'])
    expect(result.current.viewpointPlayerId).toBe(9)
  })

  it('returns all ordered players by default', () => {
    seedShellViewpoint(1)
    useFleetPlayerVisibilityStore.getState().setFleetPlayerVisible(9, false)

    const { result } = renderHook(() => useOrderedFleetPlayers(), {
      wrapper: createWrapper(),
    })

    expect(result.current.players.map((player) => player.playerId)).toEqual([8, 9])
    expect(result.current.isPlayerVisible(9)).toBe(false)
  })

  it('filters to visible players when visibleOnly is true', () => {
    seedShellViewpoint(1)
    useFleetPlayerVisibilityStore.getState().setFleetPlayerVisible(9, false)

    const { result } = renderHook(() => useOrderedFleetPlayers({ visibleOnly: true }), {
      wrapper: createWrapper(),
    })

    expect(result.current.players.map((player) => player.name)).toEqual(['Alice'])
  })

  it('keeps viewpoint ordering when filtering visible players', () => {
    seedShellViewpoint(2)
    useFleetPlayerVisibilityStore.getState().setFleetPlayerVisible(8, false)

    const { result } = renderHook(() => useOrderedFleetPlayers({ visibleOnly: true }), {
      wrapper: createWrapper(),
    })

    expect(result.current.players.map((player) => player.name)).toEqual(['Bob'])
  })
})
