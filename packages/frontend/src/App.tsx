import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  buildPerspectivesFromGameInfo,
  getLatestTurnFromGameInfo,
  getSectorDisplayNameFromGameInfo,
  isGameFinishedFromGameInfo,
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
import { AnalyticsBar } from './components/AnalyticsBar'
import { MainArea } from './components/MainArea'
import {
  fetchAnalytics,
  fetchShellBootstrap,
  fetchStoredGameInfo,
  refreshGameInfo,
  type ConnectionsMapParams,
  type GameInfoResponse,
} from './api/bff'
import { useSessionStore } from './stores/session'
import { useShellStore } from './stores/shell'
import { useShellContext } from './shell'
import { shouldRetryTanStackQuery } from './lib/queryRetry'

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
  const [enabledIds, setEnabledIds] = useState<Set<string>>(new Set())
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
    onTurnChange: handleShellTurnChange,
  } = useShellContext({ reportShellError: addShellError })

  const refreshGameMutation = useMutation({
    mutationFn: async (vars: {
      gameId: string
      username: string
      password?: string
    }): Promise<
      | { source: 'refresh'; gameInfo: GameInfoResponse }
      | { source: 'storage'; load: StorageGameLoadResult }
    > => {
      const username = vars.username.trim()
      if (username) {
        return {
          source: 'refresh',
          gameInfo: await refreshGameInfo(vars.gameId, { username, password: vars.password }),
        }
      }
      return { source: 'storage', load: await loadGameFromStorage(vars.gameId) }
    },
    retry: false,
    onSuccess: (data, vars) => {
      if (data.source === 'storage') {
        const { load } = data
        const perspectives = buildPerspectivesFromGameInfo(load.gameInfo)
        applyGameInfoRefresh(
          vars.gameId,
          {
            turn: load.turn,
            perspectives,
            isGameFinished: isGameFinishedFromGameInfo(load.gameInfo),
            sectorDisplayName: getSectorDisplayNameFromGameInfo(load.gameInfo),
          },
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
        const perspectives = buildPerspectivesFromGameInfo(gameInfo)
        const isGameFinished = isGameFinishedFromGameInfo(gameInfo)
        applyGameInfoRefresh(vars.gameId, {
          turn: latestTurn,
          perspectives,
          isGameFinished,
          sectorDisplayName: getSectorDisplayNameFromGameInfo(gameInfo),
        }, {
          selectableTurnMax: selectableTurnMaxForShell(latestTurn),
        })
      }

      void queryClient.invalidateQueries({ queryKey: ['bff', 'games'] })
    },
    onError: (err) => {
      const message =
        err instanceof Error ? err.message : typeof err === 'string' ? err : 'Game refresh failed'
      addShellError(message)
    },
  })

  useEffect(() => {
    resetPerspectiveOverride()
    if (loginName?.trim()) {
      clearStorageOnlyLoad()
    }
  }, [loginName, resetPerspectiveOverride, clearStorageOnlyLoad])

  const handleCommitGameSelection = useCallback(
    (gameId: string) => {
      const { name, password } = useSessionStore.getState()
      refreshGameMutation.mutate({
        gameId,
        username: name?.trim() ?? '',
        password: password || undefined,
      })
    },
    [refreshGameMutation]
  )

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
      const perspectives = buildPerspectivesFromGameInfo(loaded.gameInfo)
      applyGameInfoRefresh(
        configuredInitialGameId,
        {
          turn: loaded.turn,
          perspectives,
          isGameFinished: isGameFinishedFromGameInfo(loaded.gameInfo),
          sectorDisplayName: getSectorDisplayNameFromGameInfo(loaded.gameInfo),
        },
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
    const perspectives = buildPerspectivesFromGameInfo(data)
    const isGameFinished = isGameFinishedFromGameInfo(data)
    applyGameInfoRefresh(configuredInitialGameId, {
      turn: latestTurn,
      perspectives,
      isGameFinished,
      sectorDisplayName: getSectorDisplayNameFromGameInfo(data),
    }, {
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

  const analytics = analyticsData?.analytics ?? []
  const enabledAnalyticIds = useMemo(
    () => analytics.filter((a) => enabledIds.has(a.id)).map((a) => a.id),
    [analytics, enabledIds]
  )
  const handleMapZoomChange = useCallback((z: number) => {
    if (Number.isFinite(z) && z > 0) setMapZoom(Math.min(40, Math.max(0.2, z)))
  }, [])
  const handleSetZoomReady = useCallback((fn: (z: number) => void) => {
    setMapZoomFromSlider.current = fn
  }, [])
  const handleMapZoomSliderChange = useCallback((z: number) => {
    setMapZoomFromSlider.current?.(z)
  }, [])

  const toggleAnalytic = (id: string) => {
    setEnabledIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="flex h-screen flex-col bg-black">
      <Header
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        mapZoom={mapZoom}
        onMapZoomSliderChange={handleMapZoomSliderChange}
        selectedGameId={selectedGameId}
        onCommitGameSelection={handleCommitGameSelection}
        isGameRefreshPending={refreshGameMutation.isPending}
        reportShellError={addShellError}
        shellTurnMax={shellTurnMax}
        shellTurnValue={selectedTurn}
        onShellTurnChange={handleShellTurnChange}
        shellViewpoints={shellViewpoints}
        shellSelectedViewpointName={shellSelectedViewpointName}
        onShellViewpointChange={handleShellViewpointChange}
      />
      <ShellErrorBar errors={shellErrors} onDismiss={dismissShellError} />
      <div className="flex min-h-0 flex-1">
        <AnalyticsBar
          analytics={analytics}
          enabledIds={enabledIds}
          onToggle={toggleAnalytic}
          viewMode={viewMode}
          connectionsMapParams={connectionsMapParams}
          onConnectionsMapParamsChange={setConnectionsMapParams}
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
