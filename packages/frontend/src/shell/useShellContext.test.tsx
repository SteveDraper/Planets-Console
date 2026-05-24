import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useShellContext } from './useShellContext'
import { useShellStore } from '../stores/shell'
import { useSessionStore } from '../stores/session'

vi.mock('../api/bff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/bff')>()
  return {
    ...actual,
    ensureTurnData: vi.fn().mockResolvedValue({ ready: true }),
    fetchStoredTurnPerspectives: vi.fn().mockResolvedValue({ perspectives: [1] }),
  }
})

import { ensureTurnData } from '../api/bff'

function createWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('useShellContext', () => {
  const reportShellError = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    useSessionStore.setState({ name: 'Alice', password: '' })
    useShellStore.setState({
      selectedGameId: null,
      gameInfoContext: null,
      selectedTurn: null,
      perspectiveOverrideName: null,
      lastShellGameId: null,
      storageOnlyLoad: false,
      storageAvailablePerspectives: null,
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('derives analyticScope and gates turn ensure until scope is complete', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    const { result, rerender } = renderHook(
      () => useShellContext({ reportShellError }),
      { wrapper: createWrapper(client) }
    )

    expect(result.current.analyticScope).toBeNull()
    expect(result.current.turnEnsureEnabled).toBe(false)
    expect(result.current.turnDataReady).toBe(false)

    useShellStore.setState({
      selectedGameId: '628580',
      gameInfoContext: {
        turn: 10,
        perspectives: [{ ordinal: 1, name: 'Alice', raceName: null }],
        isGameFinished: true,
        sectorDisplayName: null,
      },
      selectedTurn: 5,
    })
    rerender()

    await waitFor(() => {
      expect(result.current.analyticScope).toEqual({
        gameId: '628580',
        turn: 5,
        perspective: 1,
      })
    })
    expect(result.current.turnEnsureEnabled).toBe(true)

    await waitFor(() => {
      expect(result.current.turnDataReady).toBe(true)
    })
    expect(ensureTurnData).toHaveBeenCalledWith('628580', {
      turn: 5,
      perspective: 1,
      username: 'Alice',
      password: undefined,
    })
  })

  it('sets turnBlockedNoLogin when scope exists without login or storage-only path', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    useSessionStore.setState({ name: '', password: '' })
    useShellStore.setState({
      selectedGameId: '628580',
      gameInfoContext: {
        turn: 10,
        perspectives: [{ ordinal: 1, name: 'Alice', raceName: null }],
        isGameFinished: true,
        sectorDisplayName: null,
      },
      selectedTurn: 5,
      storageOnlyLoad: false,
    })

    const { result } = renderHook(() => useShellContext({ reportShellError }), {
      wrapper: createWrapper(client),
    })

    expect(result.current.analyticScope).not.toBeNull()
    expect(result.current.turnBlockedNoLogin).toBe(true)
    expect(result.current.turnEnsureEnabled).toBe(false)
  })

  it('reports turn ensure failures via reportShellError', async () => {
    vi.mocked(ensureTurnData).mockRejectedValueOnce(new Error('Ensure failed'))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    useShellStore.setState({
      selectedGameId: '628580',
      gameInfoContext: {
        turn: 10,
        perspectives: [{ ordinal: 1, name: 'Alice', raceName: null }],
        isGameFinished: true,
        sectorDisplayName: null,
      },
      selectedTurn: 5,
    })

    renderHook(() => useShellContext({ reportShellError }), {
      wrapper: createWrapper(client),
    })

    await waitFor(() => {
      expect(reportShellError).toHaveBeenCalledWith('Ensure failed')
    })
  })
})
