import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  buildPerspectivesFromGameInfo,
  getLatestTurnFromGameInfo,
  getSectorDisplayNameFromGameInfo,
  isGameFinishedFromGameInfo,
  LOGIN_REQUIRED_FOR_GAME_SELECTION,
  perspectiveOrdinalForName,
  perspectiveNameForOrdinal,
  viewpointNameForLogin,
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
  ensureTurnData,
  fetchAnalytics,
  fetchShellBootstrap,
  fetchStoredGameInfo,
  fetchStoredTurnPerspectives,
  refreshGameInfo,
  type AnalyticShellScope,
  type ConnectionsMapParams,
  type GameInfoResponse,
} from './api/bff'
import { useSessionStore } from './stores/session'
import { useShellStore } from './stores/shell'
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

  const selectedGameId = useShellStore((s) => s.selectedGameId)
  const gameInfoContext = useShellStore((s) => s.gameInfoContext)
  const selectedTurn = useShellStore((s) => s.selectedTurn)
  const perspectiveOverrideName = useShellStore((s) => s.perspectiveOverrideName)
  const applyGameInfoRefresh = useShellStore((s) => s.applyGameInfoRefresh)
  const setPerspectiveOverrideName = useShellStore((s) => s.setPerspectiveOverrideName)
  const setSelectedTurn = useShellStore((s) => s.setSelectedTurn)
  const resetPerspectiveOverride = useShellStore((s) => s.resetPerspectiveOverride)
  const storageOnlyLoad = useShellStore((s) => s.storageOnlyLoad)
  const storageAvailablePerspectives = useShellStore((s) => s.storageAvailablePerspectives)
  const setStorageAvailablePerspectives = useShellStore((s) => s.setStorageAvailablePerspectives)
  const clearStorageOnlyLoad = useShellStore((s) => s.clearStorageOnlyLoad)

  const addShellError = useCallback((message: string) => {
    setShellErrors((prev) => [...prev, { id: crypto.randomUUID(), message }])
  }, [])

  const dismissShellError = useCallback((id: string) => {
    setShellErrors((prev) => prev.filter((e) => e.id !== id))
  }, [])

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
        applyGameInfoRefresh(vars.gameId, {
          turn: latestTurn,
          perspectives,
          isGameFinished: isGameFinishedFromGameInfo(gameInfo),
          sectorDisplayName: getSectorDisplayNameFromGameInfo(gameInfo),
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
        password: password?.trim() ? password : undefined,
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
    applyGameInfoRefresh(configuredInitialGameId, {
      turn: latestTurn,
      perspectives,
      isGameFinished: isGameFinishedFromGameInfo(data),
      sectorDisplayName: getSectorDisplayNameFromGameInfo(data),
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

  const shellTurnMax = useMemo(() => {
    const t = gameInfoContext?.turn
    if (t == null || !Number.isFinite(t) || t < 1) return null
    return Math.floor(t)
  }, [gameInfoContext?.turn])

  const handleShellTurnChange = useCallback(
    (n: number) => {
      if (shellTurnMax == null) return
      const clamped = Math.min(Math.max(1, Math.round(n)), shellTurnMax)
      setSelectedTurn(clamped)
    },
    [shellTurnMax, setSelectedTurn]
  )

  const shellPerspectiveNames = useMemo(
    () => gameInfoContext?.perspectives.map((p) => p.name) ?? [],
    [gameInfoContext?.perspectives]
  )

  const shellDefaultViewpointName = useMemo(
    () =>
      gameInfoContext
        ? viewpointNameForLogin(gameInfoContext.perspectives, loginName)
        : null,
    [gameInfoContext, loginName]
  )

  const shellViewpoints = useMemo(() => {
    const perspectives = gameInfoContext?.perspectives ?? []
    if (perspectives.length === 0) {
      return []
    }
    const loginTrimmedLocal = loginName?.trim() ?? ''
    const storageSlots =
      storageOnlyLoad && loginTrimmedLocal === ''
        ? new Set(storageAvailablePerspectives ?? [])
        : null
    if (storageSlots != null) {
      return perspectives.map((row) => ({
        name: row.name,
        raceName: row.raceName,
        disabled: !storageSlots.has(row.ordinal),
      }))
    }
    const finished = gameInfoContext?.isGameFinished ?? true
    if (finished) {
      return perspectives.map((row) => ({
        name: row.name,
        raceName: row.raceName,
        disabled: false,
      }))
    }
    const allowed = shellDefaultViewpointName
    return perspectives.map((row) => ({
      name: row.name,
      raceName: row.raceName,
      disabled: allowed == null ? true : row.name !== allowed,
    }))
  }, [
    gameInfoContext?.perspectives,
    gameInfoContext?.isGameFinished,
    shellDefaultViewpointName,
    storageOnlyLoad,
    storageAvailablePerspectives,
    loginName,
  ])

  useEffect(() => {
    if (!gameInfoContext || gameInfoContext.isGameFinished) {
      return
    }
    const allowed = viewpointNameForLogin(gameInfoContext.perspectives, loginName)
    const override = perspectiveOverrideName
    if (override == null || allowed == null) {
      return
    }
    if (override.toLowerCase() !== allowed.toLowerCase()) {
      setPerspectiveOverrideName(null)
    }
  }, [
    gameInfoContext,
    loginName,
    perspectiveOverrideName,
    setPerspectiveOverrideName,
  ])

  const shellSelectedViewpointName = useMemo(() => {
    if (shellPerspectiveNames.length === 0) return null
    const loginTrimmedLocal = loginName?.trim() ?? ''
    if (storageOnlyLoad && loginTrimmedLocal === '') {
      const preferred = perspectiveOverrideName
      if (preferred && shellPerspectiveNames.includes(preferred)) return preferred
      const firstStored = storageAvailablePerspectives?.[0]
      if (firstStored != null) {
        const name = perspectiveNameForOrdinal(
          gameInfoContext?.perspectives ?? [],
          firstStored
        )
        if (name && shellPerspectiveNames.includes(name)) return name
      }
      return shellPerspectiveNames[0] ?? null
    }
    const finished = gameInfoContext?.isGameFinished ?? true
    if (!finished) {
      if (shellDefaultViewpointName && shellPerspectiveNames.includes(shellDefaultViewpointName)) {
        return shellDefaultViewpointName
      }
      return shellPerspectiveNames[0] ?? null
    }
    const preferred = perspectiveOverrideName ?? shellDefaultViewpointName
    if (preferred && shellPerspectiveNames.includes(preferred)) return preferred
    return shellPerspectiveNames[0] ?? null
  }, [
    shellPerspectiveNames,
    perspectiveOverrideName,
    shellDefaultViewpointName,
    gameInfoContext?.isGameFinished,
    gameInfoContext?.perspectives,
    storageOnlyLoad,
    storageAvailablePerspectives,
    loginName,
  ])

  const handleShellViewpointChange = useCallback(
    (name: string) => {
      const loginTrimmedLocal = loginName?.trim() ?? ''
      if (storageOnlyLoad && loginTrimmedLocal === '') {
        const ordinal = perspectiveOrdinalForName(gameInfoContext?.perspectives ?? [], name)
        if (ordinal == null || !(storageAvailablePerspectives ?? []).includes(ordinal)) {
          return
        }
        setPerspectiveOverrideName(name)
        return
      }
      if (gameInfoContext && !gameInfoContext.isGameFinished) {
        const allowed = viewpointNameForLogin(gameInfoContext.perspectives, loginName)
        if (
          allowed == null ||
          name.trim().toLowerCase() !== allowed.trim().toLowerCase()
        ) {
          return
        }
      }
      setPerspectiveOverrideName(name)
    },
    [
      gameInfoContext,
      loginName,
      setPerspectiveOverrideName,
      storageOnlyLoad,
      storageAvailablePerspectives,
    ]
  )

  const analyticScope = useMemo((): AnalyticShellScope | null => {
    if (!selectedGameId || selectedTurn == null) return null
    const ordinal = perspectiveOrdinalForName(
      gameInfoContext?.perspectives ?? [],
      shellSelectedViewpointName
    )
    if (ordinal == null) return null
    return {
      gameId: selectedGameId,
      turn: selectedTurn,
      perspective: ordinal,
    }
  }, [selectedGameId, selectedTurn, gameInfoContext?.perspectives, shellSelectedViewpointName])

  const loginTrimmed = loginName?.trim() ?? ''
  const turnEnsureEnabled =
    analyticScope != null && (loginTrimmed !== '' || storageOnlyLoad)

  const {
    isSuccess: turnEnsureSuccess,
    isPending: turnEnsurePending,
    isError: turnEnsureIsError,
    error: turnEnsureError,
  } = useQuery({
    queryKey: [
      'bff',
      'turnData',
      analyticScope?.gameId ?? '',
      analyticScope?.turn ?? 0,
      analyticScope?.perspective ?? 0,
      loginTrimmed,
    ] as const,
    queryFn: () => {
      const { name, password } = useSessionStore.getState()
      const user = name?.trim() ?? ''
      if (!analyticScope) {
        throw new Error('Missing shell scope')
      }
      return ensureTurnData(analyticScope.gameId, {
        turn: analyticScope.turn,
        perspective: analyticScope.perspective,
        username: user,
        password: password?.trim() ? password : undefined,
      })
    },
    enabled: turnEnsureEnabled,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })

  const turnEnsureFailureSeen = useRef(false)
  useEffect(() => {
    if (turnEnsureIsError && turnEnsureError) {
      if (!turnEnsureFailureSeen.current) {
        turnEnsureFailureSeen.current = true
        addShellError(
          turnEnsureError instanceof Error
            ? turnEnsureError.message
            : 'Failed to load turn data'
        )
      }
    } else {
      turnEnsureFailureSeen.current = false
    }
  }, [turnEnsureIsError, turnEnsureError, addShellError])

  const storageTurnResyncSeen = useRef<{ gameId: string; turn: number } | null>(null)
  useEffect(() => {
    if (!storageOnlyLoad || loginTrimmed || !selectedGameId || selectedTurn == null) {
      storageTurnResyncSeen.current = null
      return
    }
    const seen = storageTurnResyncSeen.current
    if (seen?.gameId === selectedGameId && seen.turn === selectedTurn) {
      return
    }
    storageTurnResyncSeen.current = { gameId: selectedGameId, turn: selectedTurn }

    let cancelled = false
    void fetchStoredTurnPerspectives(selectedGameId, selectedTurn)
      .then(({ perspectives }) => {
        if (cancelled) return
        if (perspectives.length === 0) {
          setStorageAvailablePerspectives([])
          addShellError(LOGIN_REQUIRED_FOR_GAME_SELECTION)
          return
        }
        setStorageAvailablePerspectives(perspectives)
        const perspectivesRows = useShellStore.getState().gameInfoContext?.perspectives ?? []
        const currentName = useShellStore.getState().perspectiveOverrideName
        const currentOrdinal = perspectiveOrdinalForName(perspectivesRows, currentName)
        if (currentOrdinal != null && perspectives.includes(currentOrdinal)) {
          return
        }
        const nextName = perspectiveNameForOrdinal(perspectivesRows, perspectives[0])
        if (nextName) {
          setPerspectiveOverrideName(nextName)
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return
        addShellError(
          err instanceof Error ? err.message : LOGIN_REQUIRED_FOR_GAME_SELECTION
        )
      })

    return () => {
      cancelled = true
    }
  }, [
    storageOnlyLoad,
    loginTrimmed,
    selectedGameId,
    selectedTurn,
    setStorageAvailablePerspectives,
    setPerspectiveOverrideName,
    addShellError,
  ])

  const turnBlockedNoLogin =
    analyticScope != null && loginTrimmed === '' && !storageOnlyLoad
  const turnDataReady = turnEnsureEnabled && turnEnsureSuccess

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
