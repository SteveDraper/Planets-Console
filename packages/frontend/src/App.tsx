import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  buildPerspectivesFromGameInfo,
  getLatestTurnFromGameInfo,
  isGameFinishedFromGameInfo,
  perspectiveOrdinalForName,
  viewpointNameForLogin,
} from './lib/gameInfoShell'
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
  refreshGameInfo,
  type AnalyticShellScope,
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
  const [shellErrors, setShellErrors] = useState<ShellErrorItem[]>([])

  const selectedGameId = useShellStore((s) => s.selectedGameId)
  const gameInfoContext = useShellStore((s) => s.gameInfoContext)
  const selectedTurn = useShellStore((s) => s.selectedTurn)
  const perspectiveOverrideName = useShellStore((s) => s.perspectiveOverrideName)
  const applyGameInfoRefresh = useShellStore((s) => s.applyGameInfoRefresh)
  const setPerspectiveOverrideName = useShellStore((s) => s.setPerspectiveOverrideName)
  const setSelectedTurn = useShellStore((s) => s.setSelectedTurn)
  const resetPerspectiveOverride = useShellStore((s) => s.resetPerspectiveOverride)

  const addShellError = useCallback((message: string) => {
    setShellErrors((prev) => [...prev, { id: crypto.randomUUID(), message }])
  }, [])

  const dismissShellError = useCallback((id: string) => {
    setShellErrors((prev) => prev.filter((e) => e.id !== id))
  }, [])

  const refreshGameMutation = useMutation({
    mutationFn: async (vars: { gameId: string; username: string; password?: string }) => {
      const username = vars.username.trim()
      if (!username) {
        throw new Error('Set login name in the header before selecting a game.')
      }
      return refreshGameInfo(vars.gameId, { username, password: vars.password })
    },
    retry: false,
    onSuccess: (data, vars) => {
      const latestTurn = getLatestTurnFromGameInfo(data)
      const perspectives = buildPerspectivesFromGameInfo(data)
      applyGameInfoRefresh(vars.gameId, {
        turn: latestTurn,
        perspectives,
        isGameFinished: isGameFinishedFromGameInfo(data),
      })

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
  }, [loginName, resetPerspectiveOverride])

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
    const names = shellPerspectiveNames
    if (names.length === 0) {
      return []
    }
    const finished = gameInfoContext?.isGameFinished ?? true
    if (finished) {
      return names.map((name) => ({ name, disabled: false }))
    }
    const allowed = shellDefaultViewpointName
    return names.map((name) => ({
      name,
      disabled: allowed == null ? true : name !== allowed,
    }))
  }, [shellPerspectiveNames, gameInfoContext?.isGameFinished, shellDefaultViewpointName])

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
  ])

  const handleShellViewpointChange = useCallback(
    (name: string) => {
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
    [gameInfoContext, loginName, setPerspectiveOverrideName]
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
  const turnEnsureEnabled = analyticScope != null && loginTrimmed !== ''

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

  const turnBlockedNoLogin = analyticScope != null && loginTrimmed === ''
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
            turnBlockedNoLogin={turnBlockedNoLogin}
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
