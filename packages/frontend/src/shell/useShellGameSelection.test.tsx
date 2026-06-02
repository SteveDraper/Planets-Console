import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useShellGameSelection } from './useShellGameSelection'
import { useShellStore } from '../stores/shell'
import { useSessionStore } from '../stores/session'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../analytics/stellar-cartography/layers'

vi.mock('../api/bff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/bff')>()
  return {
    ...actual,
    refreshGameInfo: vi.fn().mockResolvedValue({
      game: { id: 99, turn: 5 },
      players: [],
    }),
    loadAllTurnsWithProgress: vi.fn().mockResolvedValue({
      game_id: 99,
      is_game_finished: false,
      turns_written: 1,
      turns_skipped: 0,
      perspectives_touched: [1],
    }),
    fetchLoadAllTurnsStatus: vi.fn().mockResolvedValue({
      game_id: 99,
      complete: false,
      is_game_finished: false,
      expected_perspectives: [1],
      latest_turn: 5,
    }),
  }
})

import { refreshGameInfo, loadAllTurnsWithProgress, type GameInfoResponse } from '../api/bff'

function createWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('useShellGameSelection', () => {
  const reportShellError = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    useSessionStore.setState({ name: 'Alice', password: 'secret', credentialsRevision: 1 })
    useShellStore.setState({
      selectedGameId: '99',
      gameInfoContext: {
        turn: 5,
        perspectives: [{ ordinal: 1, name: 'Alice', raceName: null }],
        isGameFinished: false,
        sectorDisplayName: null,
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
      },
      selectedTurn: 5,
      perspectiveOverrideName: null,
      lastShellGameId: null,
      storageOnlyLoad: false,
      storageAvailablePerspectives: null,
    })
  })

  it('marks load-all pending during commit with load-all option before refresh finishes', async () => {
    let resolveRefresh!: (value: GameInfoResponse) => void
    vi.mocked(refreshGameInfo).mockImplementation(
      () =>
        new Promise<GameInfoResponse>((resolve) => {
          resolveRefresh = resolve
        })
    )

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { result } = renderHook(() => useShellGameSelection({ reportShellError }), {
      wrapper: createWrapper(client),
    })

    act(() => {
      result.current.handleCommitGameSelection('99', { loadAllTurns: true })
    })

    await waitFor(() => {
      expect(result.current.isLoadAllTurnsPending).toBe(true)
      expect(result.current.isGameRefreshPending).toBe(true)
    })

    await act(async () => {
      resolveRefresh({ game: { id: 99, turn: 5 }, players: [] })
    })

    await waitFor(() => {
      expect(loadAllTurnsWithProgress).toHaveBeenCalled()
    })
  })

  it('does not mark load-all pending during refresh without load-all option', async () => {
    let resolveRefresh!: (value: GameInfoResponse) => void
    vi.mocked(refreshGameInfo).mockImplementation(
      () =>
        new Promise<GameInfoResponse>((resolve) => {
          resolveRefresh = resolve
        })
    )

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { result } = renderHook(() => useShellGameSelection({ reportShellError }), {
      wrapper: createWrapper(client),
    })

    act(() => {
      result.current.handleCommitGameSelection('99')
    })

    await waitFor(() => {
      expect(result.current.isGameRefreshPending).toBe(true)
      expect(result.current.isLoadAllTurnsPending).toBe(false)
    })

    await act(async () => {
      resolveRefresh({ game: { id: 99, turn: 5 }, players: [] })
    })
  })

  it('disables load-all when status reports complete', async () => {
    const { fetchLoadAllTurnsStatus } = await import('../api/bff')
    vi.mocked(fetchLoadAllTurnsStatus).mockResolvedValue({
      game_id: 99,
      complete: true,
      is_game_finished: true,
      expected_perspectives: [1],
      latest_turn: 10,
    })

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { result } = renderHook(() => useShellGameSelection({ reportShellError }), {
      wrapper: createWrapper(client),
    })

    await waitFor(() => {
      expect(result.current.isLoadAllTurnsDisabled).toBe(true)
    })
  })

  it('reports shell error when load-all is triggered without login', async () => {
    useSessionStore.setState({ name: '', password: '', credentialsRevision: 0 })

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { result } = renderHook(() => useShellGameSelection({ reportShellError }), {
      wrapper: createWrapper(client),
    })

    act(() => {
      result.current.handleLoadAllTurns()
    })

    expect(reportShellError).toHaveBeenCalled()
    expect(loadAllTurnsWithProgress).not.toHaveBeenCalled()
  })

  it('runs load-all mutation with session credentials', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { result } = renderHook(() => useShellGameSelection({ reportShellError }), {
      wrapper: createWrapper(client),
    })

    await act(async () => {
      result.current.handleLoadAllTurns()
    })

    await waitFor(() => {
      expect(loadAllTurnsWithProgress).toHaveBeenCalledWith(
        '99',
        { username: 'Alice', password: 'secret' },
        expect.any(Function)
      )
    })
  })

  it('reports shell error when final turn load fails for some perspectives', async () => {
    useShellStore.setState({
      gameInfoContext: {
        turn: 5,
        perspectives: [
          { ordinal: 1, name: 'Alice', raceName: null },
          { ordinal: 2, name: 'Bob', raceName: null },
        ],
        isGameFinished: true,
        sectorDisplayName: null,
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
      },
    })
    vi.mocked(loadAllTurnsWithProgress).mockResolvedValue({
      game_id: 99,
      is_game_finished: true,
      turns_written: 10,
      turns_skipped: 0,
      perspectives_touched: [1, 2],
      final_turn_load_failures: [2],
    })

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { result } = renderHook(() => useShellGameSelection({ reportShellError }), {
      wrapper: createWrapper(client),
    })

    await act(async () => {
      result.current.handleLoadAllTurns()
    })

    await waitFor(() => {
      expect(reportShellError).toHaveBeenCalledWith(
        'Load-all finished but the final turn could not be fetched for Bob (perspective 2). Retry Load all turns or change turn to load the latest turn manually.'
      )
    })
  })

  it('does not report shell error when final turn load succeeds for all perspectives', async () => {
    vi.mocked(loadAllTurnsWithProgress).mockResolvedValue({
      game_id: 99,
      is_game_finished: true,
      turns_written: 10,
      turns_skipped: 0,
      perspectives_touched: [1],
      final_turn_load_failures: [],
    })

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { result } = renderHook(() => useShellGameSelection({ reportShellError }), {
      wrapper: createWrapper(client),
    })

    await act(async () => {
      result.current.handleLoadAllTurns()
    })

    await waitFor(() => {
      expect(loadAllTurnsWithProgress).toHaveBeenCalled()
    })
    expect(reportShellError).not.toHaveBeenCalled()
  })
})
