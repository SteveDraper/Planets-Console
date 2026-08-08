import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useShellContext } from './useShellContext'
import { useShellStore } from '../stores/shell'
import { useSessionStore } from '../stores/session'
import {
  installPlayerColorsStorePort,
  resetPlayerColorsStoreState,
  usePlayerColorsStore,
} from '../stores/playerColors'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../analytics/stellar-cartography/layers'
import { DiplomacyTier } from '../lib/diplomacyTier'
import { perspectiveRow } from '../lib/perspectiveRowTestFixtures'
import { resetPlayerColorResolutionPort } from '../lib/playerColor'

vi.mock('../api/bff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/bff')>()
  return {
    ...actual,
    ensureTurnData: vi.fn().mockResolvedValue({
      ready: true,
      turnUsernamesByPlayerId: new Map(),
      turnRelations: [],
    }),
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
    resetPlayerColorsStoreState()
    resetPlayerColorResolutionPort()
    installPlayerColorsStorePort()
    useSessionStore.setState({ name: 'Alice', password: '', credentialsRevision: 0 })
    useShellStore.setState({
      selectedGameId: null,
      gameInfoContext: null,
      selectedTurn: null,
      perspectiveOverrideOrdinal: null,
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
        perspectives: [perspectiveRow(1, 'Alice')],
        isGameFinished: true,
        sectorDisplayName: null,
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
        homeworldInactiveReason: null,
      },
      selectedTurn: 5,
    })
    rerender()

    await waitFor(() => {
      expect(result.current.analyticScope).toEqual({
        gameId: '628580',
        turn: 5,
        perspective: 1,
        username: 'Alice',
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
    })
  })

  it('sends username only to ensureTurnData (no password)', async () => {
    useSessionStore.getState().adoptLoginName('Alice')
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    useShellStore.setState({
      selectedGameId: '628580',
      gameInfoContext: {
        turn: 10,
        perspectives: [perspectiveRow(1, 'Alice')],
        isGameFinished: true,
        sectorDisplayName: null,
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
        homeworldInactiveReason: null,
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
        perspectives: [perspectiveRow(1, 'Alice')],
        isGameFinished: true,
        sectorDisplayName: null,
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
        homeworldInactiveReason: null,
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
        perspectives: [perspectiveRow(1, 'Alice')],
        isGameFinished: true,
        sectorDisplayName: null,
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
        homeworldInactiveReason: null,
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
      .mockResolvedValueOnce({
        ready: true,
        turnUsernamesByPlayerId: new Map(),
        turnRelations: [],
      })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    useShellStore.setState({
      selectedGameId: '628580',
      gameInfoContext: {
        turn: 10,
        perspectives: [perspectiveRow(1, 'Alice')],
        isGameFinished: true,
        sectorDisplayName: null,
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
        homeworldInactiveReason: null,
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

    useSessionStore.getState().adoptLoginName('Alice')

    await waitFor(() => {
      expect(result.current.turnDataReady).toBe(true)
    })
    expect(ensureTurnData).toHaveBeenCalledTimes(2)
    expect(ensureTurnData).toHaveBeenLastCalledWith('628580', {
      turn: 5,
      perspective: 1,
      username: 'Alice',
    })
  })

  it('reports turn ensure failures via reportShellError', async () => {
    vi.mocked(ensureTurnData).mockRejectedValueOnce(new Error('Ensure failed'))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    useShellStore.setState({
      selectedGameId: '628580',
      gameInfoContext: {
        turn: 10,
        perspectives: [perspectiveRow(1, 'Alice')],
        isGameFinished: true,
        sectorDisplayName: null,
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
        homeworldInactiveReason: null,
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
        perspectives: [perspectiveRow(1, 'Alice')],
        isGameFinished: true,
        sectorDisplayName: null,
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
        homeworldInactiveReason: null,
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
        perspectives: [perspectiveRow(1, 'Alice')],
        isGameFinished: true,
        sectorDisplayName: null,
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
        homeworldInactiveReason: null,
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
        perspectives: [perspectiveRow(1, 'Alice'), perspectiveRow(2, 'Bob')],
        isGameFinished: false,
        sectorDisplayName: null,
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
        homeworldInactiveReason: null,
      },
      selectedTurn: 5,
      storageOnlyLoad: true,
      storageAvailablePerspectives: [2],
      perspectiveOverrideOrdinal: 2,
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
      expect(result.current.selectedViewpointOrdinal).toBe(0)
      expect(result.current.analyticScope).toEqual({
        gameId: '628580',
        turn: 6,
        perspective: 0,
      })
    })
  })

  it('installs player color paint context from ensure turn relations', async () => {
    vi.mocked(ensureTurnData).mockResolvedValue({
      ready: true,
      turnUsernamesByPlayerId: new Map(),
      turnRelations: [
        {
          playerid: 10,
          playertoid: 20,
          relationfrom: DiplomacyTier.SAFE_PASSAGE,
          relationto: DiplomacyTier.AMBASSADOR,
        },
        {
          playerid: 10,
          playertoid: 30,
          relationfrom: DiplomacyTier.NONE,
          relationto: DiplomacyTier.NONE,
        },
        {
          playerid: 20,
          playertoid: 10,
          relationfrom: DiplomacyTier.FULL_ALLIANCE,
          relationto: DiplomacyTier.SAFE_PASSAGE,
        },
      ],
    })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    useShellStore.setState({
      selectedGameId: '628580',
      gameInfoContext: {
        turn: 10,
        perspectives: [
          perspectiveRow(1, 'Alice', { playerId: 10 }),
          perspectiveRow(2, 'Bob', { playerId: 20 }),
          perspectiveRow(3, 'Carol', { playerId: 30 }),
        ],
        isGameFinished: true,
        sectorDisplayName: null,
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
        homeworldInactiveReason: null,
      },
      selectedTurn: 5,
    })

    renderHook(() => useShellContext({ reportShellError }), {
      wrapper: createWrapper(client),
    })

    await waitFor(() => {
      expect(usePlayerColorsStore.getState().viewpointPlayerId).toBe(10)
    })
    const paint = usePlayerColorsStore.getState()
    expect([...paint.inboundRelationFromByPlayerId.entries()]).toEqual([
      [20, DiplomacyTier.SAFE_PASSAGE],
      [30, DiplomacyTier.NONE],
    ])
    expect(paint.rosterPlayerIds).toEqual([10, 20, 30])
    expect(paint.paintSnapshot.viewpointPlayerId).toBe(10)
    expect(paint.paintSnapshot.inCircleMemberIds).toEqual([10, 20])
    expect(paint.paintSnapshot.outOfCircleMemberIds).toEqual([30])
  })

  it('clears player color paint context when turn ensure is no longer ready', async () => {
    vi.mocked(ensureTurnData).mockResolvedValue({
      ready: true,
      turnUsernamesByPlayerId: new Map(),
      turnRelations: [
        {
          playerid: 10,
          playertoid: 20,
          relationfrom: DiplomacyTier.SAFE_PASSAGE,
          relationto: DiplomacyTier.NONE,
        },
      ],
    })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    useShellStore.setState({
      selectedGameId: '628580',
      gameInfoContext: {
        turn: 10,
        perspectives: [
          perspectiveRow(1, 'Alice', { playerId: 10 }),
          perspectiveRow(2, 'Bob', { playerId: 20 }),
        ],
        isGameFinished: true,
        sectorDisplayName: null,
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
        homeworldInactiveReason: null,
      },
      selectedTurn: 5,
    })

    const { rerender } = renderHook(() => useShellContext({ reportShellError }), {
      wrapper: createWrapper(client),
    })

    await waitFor(() => {
      expect(usePlayerColorsStore.getState().viewpointPlayerId).toBe(10)
    })

    useShellStore.setState({
      selectedGameId: null,
      gameInfoContext: null,
      selectedTurn: null,
    })
    rerender()

    await waitFor(() => {
      expect(usePlayerColorsStore.getState().viewpointPlayerId).toBeNull()
    })
    expect(usePlayerColorsStore.getState().rosterPlayerIds).toEqual([])
    expect(usePlayerColorsStore.getState().inboundRelationFromByPlayerId.size).toBe(0)
  })
})
