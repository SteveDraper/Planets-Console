import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useShellContext } from './useShellContext'
import { useShellStore } from '../stores/shell'
import { useSessionStore } from '../stores/session'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../analytics/stellar-cartography/layers'

vi.mock('../api/bff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/bff')>()
  return {
    ...actual,
    ensureTurnData: vi.fn().mockResolvedValue({ ready: true }),
    fetchStoredTurnPerspectives: vi.fn().mockResolvedValue({ perspectives: [1] }),
  }
})

import { ensureTurnData, fetchStoredTurnPerspectives } from '../api/bff'

function createWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('useShellContext', () => {
  const reportShellError = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    useSessionStore.setState({ name: 'Alice', password: '', credentialsRevision: 0 })
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
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
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

  it('sends trimmed password to ensureTurnData', async () => {
    useSessionStore.getState().setCredentials('Alice', '  secret  ')
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    useShellStore.setState({
      selectedGameId: '628580',
      gameInfoContext: {
        turn: 10,
        perspectives: [{ ordinal: 1, name: 'Alice', raceName: null }],
        isGameFinished: true,
        sectorDisplayName: null,
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
      },
      selectedTurn: 5,
    })

    renderHook(() => useShellContext({ reportShellError }), {
      wrapper: createWrapper(client),
    })

    await waitFor(() => {
      expect(ensureTurnData).toHaveBeenCalledWith('628580', {
        turn: 5,
        perspective: 1,
        username: 'Alice',
        password: 'secret',
      })
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
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
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

  it('retries storage perspective resync after effect cleanup before fetch completes', async () => {
    useSessionStore.setState({ name: '', password: '', credentialsRevision: 0 })
    let resolveFetch!: (value: { perspectives: number[] }) => void
    vi.mocked(fetchStoredTurnPerspectives).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveFetch = resolve
        })
    )
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    useShellStore.setState({
      selectedGameId: '628580',
      gameInfoContext: {
        turn: 10,
        perspectives: [{ ordinal: 1, name: 'Alice', raceName: null }],
        isGameFinished: true,
        sectorDisplayName: null,
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
      },
      selectedTurn: 5,
      storageOnlyLoad: true,
      storageAvailablePerspectives: null,
    })

    const { unmount } = renderHook(() => useShellContext({ reportShellError }), {
      wrapper: createWrapper(client),
    })

    await waitFor(() => {
      expect(fetchStoredTurnPerspectives).toHaveBeenCalledTimes(1)
    })
    unmount()

    renderHook(() => useShellContext({ reportShellError }), {
      wrapper: createWrapper(client),
    })

    await waitFor(() => {
      expect(fetchStoredTurnPerspectives).toHaveBeenCalledTimes(2)
    })
    resolveFetch({ perspectives: [1] })
  })

  it('refetches turn ensure when credentials revision changes', async () => {
    useSessionStore.setState({ name: 'Alice', password: 'wrong', credentialsRevision: 1 })
    vi.mocked(ensureTurnData)
      .mockRejectedValueOnce(new Error('Bad password'))
      .mockResolvedValueOnce({ ready: true })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    useShellStore.setState({
      selectedGameId: '628580',
      gameInfoContext: {
        turn: 10,
        perspectives: [{ ordinal: 1, name: 'Alice', raceName: null }],
        isGameFinished: true,
        sectorDisplayName: null,
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
      },
      selectedTurn: 5,
    })

    const { result } = renderHook(() => useShellContext({ reportShellError }), {
      wrapper: createWrapper(client),
    })

    await waitFor(() => {
      expect(result.current.turnEnsureIsError).toBe(true)
    })
    expect(ensureTurnData).toHaveBeenCalledTimes(1)

    useSessionStore.getState().setCredentials('Alice', 'correct')

    await waitFor(() => {
      expect(result.current.turnDataReady).toBe(true)
    })
    expect(ensureTurnData).toHaveBeenCalledTimes(2)
    expect(ensureTurnData).toHaveBeenLastCalledWith('628580', {
      turn: 5,
      perspective: 1,
      username: 'Alice',
      password: 'correct',
    })
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
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
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

  it('setTurn clamps to minimum 1 and allows future turns beyond shellTurnMax', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    useShellStore.setState({
      selectedGameId: '628580',
      gameInfoContext: {
        turn: 10,
        perspectives: [{ ordinal: 1, name: 'Alice', raceName: null }],
        isGameFinished: true,
        sectorDisplayName: null,
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
      },
      selectedTurn: 5,
    })

    const { result } = renderHook(() => useShellContext({ reportShellError }), {
      wrapper: createWrapper(client),
    })

    act(() => {
      result.current.setTurn(0)
    })
    expect(useShellStore.getState().selectedTurn).toBe(1)

    act(() => {
      result.current.setTurn(12)
    })
    expect(useShellStore.getState().selectedTurn).toBe(12)
    expect(result.current.isFuture).toBe(true)
    expect(result.current.futureTurnOffset).toBe(2)
  })

  it('stepTurn delegates to setTurn and clamps decrement at 1', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    useShellStore.setState({
      selectedGameId: '628580',
      gameInfoContext: {
        turn: 10,
        perspectives: [{ ordinal: 1, name: 'Alice', raceName: null }],
        isGameFinished: true,
        sectorDisplayName: null,
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
      },
      selectedTurn: 5,
    })

    const { result } = renderHook(() => useShellContext({ reportShellError }), {
      wrapper: createWrapper(client),
    })

    act(() => {
      result.current.stepTurn(1)
    })
    expect(useShellStore.getState().selectedTurn).toBe(6)

    act(() => {
      result.current.stepTurn(-10)
    })
    expect(useShellStore.getState().selectedTurn).toBe(1)
  })

  it('resyncs to spectator when turn change stores only pseudo perspective 0', async () => {
    useSessionStore.setState({ name: '', password: '', credentialsRevision: 0 })
    vi.mocked(fetchStoredTurnPerspectives).mockImplementation((_gameId, turn) =>
      Promise.resolve({ perspectives: turn === 5 ? [2] : [0] })
    )
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    useShellStore.setState({
      selectedGameId: '628580',
      gameInfoContext: {
        turn: 10,
        perspectives: [
          { ordinal: 1, name: 'Alice', raceName: null },
          { ordinal: 2, name: 'Bob', raceName: null },
        ],
        isGameFinished: false,
        sectorDisplayName: null,
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
      },
      selectedTurn: 5,
      storageOnlyLoad: true,
      storageAvailablePerspectives: [2],
      perspectiveOverrideName: 'Bob',
    })

    const { result, rerender } = renderHook(() => useShellContext({ reportShellError }), {
      wrapper: createWrapper(client),
    })

    await waitFor(() => {
      expect(fetchStoredTurnPerspectives).toHaveBeenCalledWith('628580', 5)
    })

    useShellStore.setState({ selectedTurn: 6 })
    rerender()

    await waitFor(() => {
      expect(fetchStoredTurnPerspectives).toHaveBeenCalledWith('628580', 6)
    })
    await waitFor(() => {
      expect(result.current.selectedViewpointName).toBe('<Spectator>')
      expect(result.current.analyticScope).toEqual({
        gameId: '628580',
        turn: 6,
        perspective: 0,
      })
    })
  })
})
