import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { Header } from './components/Header'
import { ShellErrorBar, type ShellErrorItem } from './components/ShellErrorBar'
import { ShellLoadAllProgressBar } from './components/ShellLoadAllProgressBar'
import { AnalyticsBar } from './components/AnalyticsBar'
import { MainArea } from './components/MainArea'
import {
  fetchAnalytics,
  fetchShellBootstrap,
  type ConnectionsMapParams,
} from './api/bff'
import { useEnabledAnalyticsStore } from './stores/enabledAnalytics'
import { useScoresTablePreferencesStore } from './stores/scoresTablePreferences'
import { useSessionStore } from './stores/session'
import { useShellStore } from './stores/shell'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from './analytics/stellar-cartography/layers'
import { useStellarCartographyTurnSummary } from './analytics/stellar-cartography/useStellarCartographyTurnSummary'
import {
  applyShellGameBootstrapResult,
  fetchShellGameBootstrap,
} from './shell/shellGameBootstrap'
import { useShellContext, useShellGameSelection } from './shell'
import { TurnKeyboardShortcuts } from './components/shell/TurnKeyboardShortcuts'
import { shouldRetryTanStackQuery } from './lib/queryRetry'
import { clampMapZoom } from './lib/mapZoom'
import { useGlobalInferencePause } from './analytics/scores/useGlobalInferencePause'
import { usePersistStoreHydrated } from './lib/usePersistStoreHydrated'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: shouldRetryTanStackQuery,
    },
  },
})

function ConsoleShell() {
  const loginName = useSessionStore((s) => s.name)
  const viewMode = useShellStore((s) => s.viewMode)
  const setViewMode = useShellStore((s) => s.setViewMode)
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
  const scoresTableParams = useScoresTablePreferencesStore((s) => s.scoresTableParams)
  const setScoresTableParams = useScoresTablePreferencesStore((s) => s.setScoresTableParams)
  const [shellErrors, setShellErrors] = useState<ShellErrorItem[]>([])

  const addShellError = useCallback((message: string) => {
    setShellErrors((prev) => [...prev, { id: crypto.randomUUID(), message }])
  }, [])

  const dismissShellError = useCallback((id: string) => {
    setShellErrors((prev) => prev.filter((e) => e.id !== id))
  }, [])

  const selectedGameId = useShellStore((s) => s.selectedGameId)
  const gameInfoContext = useShellStore((s) => s.gameInfoContext)
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
    selectedViewpointOrdinal: shellSelectedViewpointOrdinal,
    onViewpointChange: handleShellViewpointChange,
    shellTurnMax,
    selectedTurn,
    isFuture,
    futureTurnOffset,
    setTurn,
    stepTurn,
  } = useShellContext({ reportShellError: addShellError })

  const {
    loadAllProgress,
    handleCommitGameSelection,
    isGameRefreshPending,
    isLoadAllTurnsDisabled,
    isLoadAllTurnsPending,
    handleLoadAllTurns,
  } = useShellGameSelection({ reportShellError: addShellError })

  const prevLoginNameRef = useRef<string | null | undefined>(undefined)
  useEffect(() => {
    const trimmed = loginName?.trim() ?? ''
    const prev = prevLoginNameRef.current
    prevLoginNameRef.current = loginName ?? null

    if (prev === undefined) {
      if (trimmed) {
        clearStorageOnlyLoad()
      }
      return
    }

    const prevTrimmed = prev?.trim() ?? ''
    if (trimmed !== prevTrimmed) {
      resetPerspectiveOverride()
      if (trimmed) {
        clearStorageOnlyLoad()
      }
    }
  }, [loginName, resetPerspectiveOverride, clearStorageOnlyLoad])

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

  const shellStoreHydrated = usePersistStoreHydrated(useShellStore)
  const scoresPreferencesHydrated = usePersistStoreHydrated(useScoresTablePreferencesStore)

  const trimmedLoginName = loginName?.trim() ?? ''

  const { data: initialGameBootstrap, isError: initialGameInfoIsError, error: initialGameInfoError } =
    useQuery({
      queryKey: ['bff', 'games', configuredInitialGameId, 'bootstrap', trimmedLoginName],
      queryFn: () => fetchShellGameBootstrap(configuredInitialGameId!, trimmedLoginName),
      enabled: shellStoreHydrated && Boolean(configuredInitialGameId) && selectedGameId === null,
      staleTime: Infinity,
      refetchOnWindowFocus: false,
      retry: false,
    })

  useEffect(() => {
    if (!initialGameBootstrap || !configuredInitialGameId) return
    if (useShellStore.getState().selectedGameId != null) return
    applyShellGameBootstrapResult(configuredInitialGameId, initialGameBootstrap, {
      storageOnlyUseDefaultViewpoint: true,
    })
  }, [initialGameBootstrap, configuredInitialGameId])

  const needsPersistedGameRestore = Boolean(selectedGameId) && gameInfoContext == null

  const {
    data: restoredGameBootstrap,
    isError: restoredGameInfoIsError,
    error: restoredGameInfoError,
  } = useQuery({
    queryKey: ['bff', 'games', selectedGameId, 'restore', trimmedLoginName],
    queryFn: () => fetchShellGameBootstrap(selectedGameId!, trimmedLoginName),
    enabled: shellStoreHydrated && needsPersistedGameRestore,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: false,
  })

  useEffect(() => {
    if (!restoredGameBootstrap || !selectedGameId) return
    if (useShellStore.getState().gameInfoContext != null) return
    applyShellGameBootstrapResult(selectedGameId, restoredGameBootstrap)
  }, [restoredGameBootstrap, selectedGameId])

  const restoredGameBootstrapFailureSeen = useRef(false)
  useEffect(() => {
    if (!restoredGameInfoIsError || !selectedGameId) {
      restoredGameBootstrapFailureSeen.current = false
      return
    }
    if (!restoredGameBootstrapFailureSeen.current) {
      restoredGameBootstrapFailureSeen.current = true
      const message =
        restoredGameInfoError instanceof Error
          ? restoredGameInfoError.message
          : 'Failed to restore selected game from storage'
      queueMicrotask(() => {
        addShellError(message)
      })
    }
  }, [restoredGameInfoIsError, restoredGameInfoError, selectedGameId, addShellError])

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
  const globalInferencePauseEnabled =
    viewMode === 'tabular' &&
    enabledIds.has('scores') &&
    scoresPreferencesHydrated &&
    scoresTableParams.includeBuildInference &&
    turnDataReady &&
    analyticScope != null
  const globalInferencePause = useGlobalInferencePause(
    analyticScope,
    globalInferencePauseEnabled
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
        isGameRefreshPending={isGameRefreshPending}
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
        shellSelectedViewpointOrdinal={shellSelectedViewpointOrdinal}
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
          scoresTableParams={scoresTableParams}
          onScoresTableParamsChange={setScoresTableParams}
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
            scoresTableParams={scoresTableParams}
            scoresPreferencesHydrated={scoresPreferencesHydrated}
            globalInferencePause={globalInferencePause}
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
