import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  buildGameInfoShellContext,
  getLatestTurnFromGameInfo,
  selectableTurnMaxForShell,
} from './lib/gameInfoShell'
import { loadGameFromStorage, type StorageGameLoadResult } from './lib/loadGameFromStorage'
import {
  QueryClient,
  QueryClientProvider,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { Header } from './components/Header'
import { ShellErrorBar, type ShellErrorItem } from './components/ShellErrorBar'
import { ShellLoadAllProgressBar } from './components/ShellLoadAllProgressBar'
import { AnalyticsBar } from './components/AnalyticsBar'
import { MainArea } from './components/MainArea'
import {
  fetchAnalytics,
  fetchShellBootstrap,
  fetchStoredGameInfo,
  fetchLoadAllTurnsStatus,
  loadAllTurnsWithProgress,
  refreshGameInfo,
  type ConnectionsMapParams,
  type GameInfoResponse,
  type LoadAllProgressUpdate,
} from './api/bff'
import type { GameSelectionOptions } from './components/GameControl'
import { LOGIN_REQUIRED_FOR_GAME_SELECTION } from './lib/gameInfoShell'
import { useEnabledAnalyticsStore } from './stores/enabledAnalytics'
import { useSessionStore } from './stores/session'
import { useShellStore } from './stores/shell'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from './analytics/stellar-cartography/layers'
import { useStellarCartographyTurnSummary } from './analytics/stellar-cartography/useStellarCartographyTurnSummary'
import { useShellContext } from './shell'
import { TurnKeyboardShortcuts } from './components/shell/TurnKeyboardShortcuts'
import { shouldRetryTanStackQuery } from './lib/queryRetry'
import { clampMapZoom } from './lib/mapZoom'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: shouldRetryTanStackQuery,
    },
  },
})

function ConsoleShell() {
  const queryClient = useQueryClient()
  const loginName = useSessionStore((s) => s.name)
  const [viewMode, setViewMode] = useState<'tabular' | 'map'>('map')
  /** React Flow zoom (same as mousewheel); 1 = 100% on slider. Updated by MapGraph. */
  const [mapZoom, setMapZoom] = useState(1)
  const setMapZoomFromSlider = useRef<(z: number) => void | undefined>(undefined)
  const enabledIdsList = useEnabledAnalyticsStore((s) => s.enabledIds)
  const toggleAnalytic = useEnabledAnalyticsStore((s) => s.toggleEnabled)
  const enabledIds = useMemo(() => new Set(enabledIdsList), [enabledIdsList])
  const [connectionsMapParams, setConnectionsMapParams] = useState<ConnectionsMapParams>({
    warpSpeed: 9,
    gravitonicMovement: false,
    flareMode: 'include',
    /** 2+ includes full static table (1- and 3-pair host rows); 1 is 1-pair rows only. */
    flareDepth: 2,
  })
  const [shellErrors, setShellErrors] = useState<ShellErrorItem[]>([])

  const addShellError = useCallback((message: string) => {
    setShellErrors((prev) => [...prev, { id: crypto.randomUUID(), message }])
  }, [])

  const dismissShellError = useCallback((id: string) => {
    setShellErrors((prev) => prev.filter((e) => e.id !== id))
  }, [])

  const selectedGameId = useShellStore((s) => s.selectedGameId)
  const gameInfoContext = useShellStore((s) => s.gameInfoContext)
  const applyGameInfoRefresh = useShellStore((s) => s.applyGameInfoRefresh)
  const resetPerspectiveOverride = useShellStore((s) => s.resetPerspectiveOverride)
  const clearStorageOnlyLoad = useShellStore((s) => s.clearStorageOnlyLoad)

  const {
    analyticScope,
    turnDataReady,
    turnEnsurePending,
    turnEnsureIsError,
    turnEnsureError,
    turnBlockedNoLogin,
    shellViewpoints,
    selectedViewpointName: shellSelectedViewpointName,
    onViewpointChange: handleShellViewpointChange,
    shellTurnMax,
    selectedTurn,
    isFuture,
    futureTurnOffset,
    setTurn,
    stepTurn,
  } = useShellContext({ reportShellError: addShellError })

  const [loadAllProgress, setLoadAllProgress] = useState<LoadAllProgressUpdate | null>(null)

  const runLoadAllTurns = useCallback(
    async (vars: { gameId: string; username: string; password?: string }) => {
      setLoadAllProgress({
        phase: 'download',
        perspective: 0,
        perspective_total: 0,
        turn: 0,
        turn_total: 0,
        message: 'Starting load…',
      })
      try {
        return await loadAllTurnsWithProgress(
          vars.gameId,
          { username: vars.username, password: vars.password },
          setLoadAllProgress
        )
      } finally {
        setLoadAllProgress(null)
      }
    },
    []
  )

  const refreshGameMutation = useMutation({
    mutationFn: async (vars: {
      gameId: string
      username: string
      password?: string
      loadAllTurns?: boolean
    }): Promise<
      | { source: 'refresh'; gameInfo: GameInfoResponse }
      | { source: 'storage'; load: StorageGameLoadResult }
    > => {
      const username = vars.username.trim()
      if (username) {
        const gameInfo = await refreshGameInfo(vars.gameId, {
          username,
          password: vars.password,
        })
        if (vars.loadAllTurns) {
          await runLoadAllTurns({
            gameId: vars.gameId,
            username,
            password: vars.password,
          })
        }
        return { source: 'refresh', gameInfo }
      }
      return { source: 'storage', load: await loadGameFromStorage(vars.gameId) }
    },
    retry: false,
    onSuccess: (data, vars) => {
      if (data.source === 'storage') {
        const { load } = data
        applyGameInfoRefresh(
          vars.gameId,
          buildGameInfoShellContext(load.gameInfo),
          {
            storageOnlyLoad: true,
            storageAvailablePerspectives: load.storedPerspectives,
            perspectiveOverrideName: load.defaultViewpointName,
          }
        )
      } else {
        clearStorageOnlyLoad()
        const { gameInfo } = data
        const latestTurn = getLatestTurnFromGameInfo(gameInfo)
        applyGameInfoRefresh(vars.gameId, buildGameInfoShellContext(gameInfo), {
          selectableTurnMax: selectableTurnMaxForShell(latestTurn),
        })
      }

      void queryClient.invalidateQueries({ queryKey: ['bff', 'games'] })
      void queryClient.invalidateQueries({
        queryKey: ['bff', 'games', vars.gameId, 'load-all-status'],
      })
    },
    onError: (err) => {
      const message =
        err instanceof Error ? err.message : typeof err === 'string' ? err : 'Game refresh failed'
      addShellError(message)
    },
  })

  const loadAllTurnsMutation = useMutation({
    mutationFn: runLoadAllTurns,
    retry: false,
    onSuccess: (_data, vars) => {
      clearStorageOnlyLoad()
      void queryClient.invalidateQueries({ queryKey: ['bff', 'games'] })
      void queryClient.invalidateQueries({
        queryKey: ['bff', 'games', vars.gameId, 'load-all-status'],
      })
    },
    onError: (err) => {
      const message =
        err instanceof Error
          ? err.message
          : typeof err === 'string'
            ? err
            : 'Load all turns failed'
      addShellError(message)
    },
  })

  const { data: loadAllTurnsStatus } = useQuery({
    queryKey: ['bff', 'games', selectedGameId, 'load-all-status', loginName?.trim() ?? ''],
    queryFn: () => fetchLoadAllTurnsStatus(selectedGameId!, loginName!.trim()),
    enabled: Boolean(selectedGameId && loginName?.trim() && gameInfoContext != null),
    staleTime: 30_000,
  })

  useEffect(() => {
    resetPerspectiveOverride()
    if (loginName?.trim()) {
      clearStorageOnlyLoad()
    }
  }, [loginName, resetPerspectiveOverride, clearStorageOnlyLoad])

  const handleCommitGameSelection = useCallback(
    (gameId: string, options?: GameSelectionOptions) => {
      const { name, password } = useSessionStore.getState()
      refreshGameMutation.mutate({
        gameId,
        username: name?.trim() ?? '',
        password: password || undefined,
        loadAllTurns: options?.loadAllTurns,
      })
    },
    [refreshGameMutation]
  )

  const handleLoadAllTurns = useCallback(() => {
    if (!selectedGameId) return
    const { name, password } = useSessionStore.getState()
    const username = name?.trim() ?? ''
    if (!username) {
      addShellError(LOGIN_REQUIRED_FOR_GAME_SELECTION)
      return
    }
    loadAllTurnsMutation.mutate({
      gameId: selectedGameId,
      username,
      password: password || undefined,
    })
  }, [selectedGameId, loadAllTurnsMutation, addShellError])

  const isLoadAllTurnsDisabled =
    !loginName?.trim() ||
    loadAllTurnsStatus?.complete === true ||
    gameInfoContext == null
  const isLoadAllTurnsPending =
    loadAllProgress != null ||
    loadAllTurnsMutation.isPending ||
    refreshGameMutation.isPending

  const { data: shellBootstrap } = useQuery({
    queryKey: ['bff', 'shell-bootstrap'],
    queryFn: fetchShellBootstrap,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })

  const configuredInitialGameId = useMemo(() => {
    const raw = shellBootstrap?.showInitialGame
    if (raw == null) return null
    const t = raw.trim()
    return t.length > 0 ? t : null
  }, [shellBootstrap?.showInitialGame])

  const { data: initialGameBootstrap, isError: initialGameInfoIsError, error: initialGameInfoError } =
    useQuery({
      queryKey: ['bff', 'games', configuredInitialGameId, 'bootstrap', loginName?.trim() ?? ''],
      queryFn: async () => {
        const gameId = configuredInitialGameId!
        const trimmedLogin = loginName?.trim() ?? ''
        if (trimmedLogin) {
          return {
            kind: 'stored-info' as const,
            data: await fetchStoredGameInfo(gameId),
          }
        }
        return {
          kind: 'storage-only' as const,
          data: await loadGameFromStorage(gameId),
        }
      },
      enabled: Boolean(configuredInitialGameId) && selectedGameId === null,
      staleTime: Infinity,
      refetchOnWindowFocus: false,
      retry: false,
    })

  useEffect(() => {
    if (!initialGameBootstrap || !configuredInitialGameId) return
    if (useShellStore.getState().selectedGameId != null) return
    if (initialGameBootstrap.kind === 'storage-only') {
      const loaded = initialGameBootstrap.data
      applyGameInfoRefresh(
        configuredInitialGameId,
        buildGameInfoShellContext(loaded.gameInfo),
        {
          storageOnlyLoad: true,
          storageAvailablePerspectives: loaded.storedPerspectives,
          perspectiveOverrideName: loaded.defaultViewpointName,
        }
      )
      return
    }
    const data = initialGameBootstrap.data
    const latestTurn = getLatestTurnFromGameInfo(data)
    applyGameInfoRefresh(configuredInitialGameId, buildGameInfoShellContext(data), {
      selectableTurnMax: selectableTurnMaxForShell(latestTurn),
    })
  }, [initialGameBootstrap, configuredInitialGameId, applyGameInfoRefresh])

  const initialGameBootstrapFailureSeen = useRef(false)
  useEffect(() => {
    if (!initialGameInfoIsError || !configuredInitialGameId) {
      initialGameBootstrapFailureSeen.current = false
      return
    }
    if (!initialGameBootstrapFailureSeen.current) {
      initialGameBootstrapFailureSeen.current = true
      const message =
        initialGameInfoError instanceof Error
          ? initialGameInfoError.message
          : 'Failed to load configured initial game from server'
      queueMicrotask(() => {
        addShellError(message)
      })
    }
  }, [
    initialGameInfoIsError,
    initialGameInfoError,
    configuredInitialGameId,
    addShellError,
  ])

  const { data: analyticsData, isPending, error: analyticsError, isError: analyticsIsError } =
    useQuery({
      queryKey: ['bff', 'analytics'],
      queryFn: fetchAnalytics,
    })

  const analyticsFailureSeen = useRef(false)
  useEffect(() => {
    if (analyticsIsError && analyticsError) {
      if (!analyticsFailureSeen.current) {
        analyticsFailureSeen.current = true
        addShellError(
          analyticsError instanceof Error
            ? analyticsError.message
            : 'Failed to load analytics'
        )
      }
    } else {
      analyticsFailureSeen.current = false
    }
  }, [analyticsIsError, analyticsError, addShellError])

  const stellarCartographyGates =
    gameInfoContext?.stellarCartographyGates ??
    EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES

  const { data: stellarCartographyTurnSummary } = useStellarCartographyTurnSummary({
    analyticScope,
    turnDataReady,
    ionStormsGate: stellarCartographyGates.ionStorms,
  })

  const ionStormCount =
    stellarCartographyGates.ionStorms && turnDataReady && analyticScope != null
      ? (stellarCartographyTurnSummary?.ionStormCount ?? null)
      : null

  const analytics = analyticsData?.analytics ?? []
  const enabledAnalyticIds = useMemo(
    () => analytics.filter((a) => enabledIds.has(a.id)).map((a) => a.id),
    [analytics, enabledIds]
  )
  const handleMapZoomChange = useCallback((z: number) => {
    setMapZoom(clampMapZoom(z))
  }, [])
  const handleSetZoomReady = useCallback((fn: (z: number) => void) => {
    setMapZoomFromSlider.current = fn
  }, [])
  const handleMapZoomSliderChange = useCallback((z: number) => {
    setMapZoomFromSlider.current?.(z)
  }, [])

  return (
    <div className="flex h-screen flex-col bg-black">
      <TurnKeyboardShortcuts
        enabled={shellTurnMax != null && selectedTurn != null}
        stepTurn={stepTurn}
      />
      <Header
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        mapZoom={mapZoom}
        onMapZoomSliderChange={handleMapZoomSliderChange}
        selectedGameId={selectedGameId}
        onCommitGameSelection={handleCommitGameSelection}
        isGameRefreshPending={refreshGameMutation.isPending}
        isLoadAllTurnsPending={isLoadAllTurnsPending}
        isLoadAllTurnsDisabled={isLoadAllTurnsDisabled}
        onLoadAllTurns={handleLoadAllTurns}
        reportShellError={addShellError}
        shellTurnMax={shellTurnMax}
        shellTurnValue={selectedTurn}
        isFuture={isFuture}
        setTurn={setTurn}
        stepTurn={stepTurn}
        shellViewpoints={shellViewpoints}
        shellSelectedViewpointName={shellSelectedViewpointName}
        onShellViewpointChange={handleShellViewpointChange}
      />
      <ShellErrorBar errors={shellErrors} onDismiss={dismissShellError} />
      {loadAllProgress ? <ShellLoadAllProgressBar progress={loadAllProgress} /> : null}
      <div className="flex min-h-0 flex-1">
        <AnalyticsBar
          analytics={analytics}
          enabledIds={enabledIds}
          onToggle={toggleAnalytic}
          viewMode={viewMode}
          connectionsMapParams={connectionsMapParams}
          onConnectionsMapParamsChange={setConnectionsMapParams}
          stellarCartographyGates={stellarCartographyGates}
          ionStormCount={ionStormCount}
        />
        {isPending ? (
          <main className="flex flex-1 items-center justify-center bg-black p-8 text-gray-400">
            Loading analytics…
          </main>
        ) : (
          <MainArea
            viewMode={viewMode}
            enabledAnalyticIds={enabledAnalyticIds}
            analytics={analytics}
            analyticScope={analyticScope}
            turnDataReady={turnDataReady}
            turnEnsurePending={turnEnsurePending}
            turnEnsureIsError={turnEnsureIsError}
            turnEnsureError={turnEnsureError}
            turnBlockedNoLogin={turnBlockedNoLogin}
            connectionsMapParams={connectionsMapParams}
            futureTurnOffset={futureTurnOffset}
            onMapZoomChange={handleMapZoomChange}
            onSetZoomReady={handleSetZoomReady}
          />
        )}
      </div>
    </div>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ConsoleShell />
    </QueryClientProvider>
  )
}
