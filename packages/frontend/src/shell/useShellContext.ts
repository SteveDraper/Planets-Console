import { useCallback, useEffect, useMemo, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ensureTurnData,
  fetchStoredTurnPerspectives,
  type AnalyticShellScope,
} from '../api/bff'
import {
  LOGIN_REQUIRED_FOR_GAME_SELECTION,
  perspectiveOrdinalForName,
  viewpointNameForStoredPerspective,
} from '../lib/gameInfoShell'
import { useSessionStore } from '../stores/session'
import { useShellStore } from '../stores/shell'
import {
  deriveAnalyticScope,
  deriveSelectedViewpointName,
  deriveShellTurnMax,
  deriveShellViewpoints,
  deriveTurnBlockedNoLogin,
  deriveTurnDataReady,
  deriveTurnEnsureEnabled,
  deriveTurnView,
  isViewpointChangeAllowed,
  shouldClearInProgressPerspectiveOverride,
  type ShellViewpointRow,
} from './shellContext'

export type UseShellContextOptions = {
  reportShellError: (message: string) => void
}

export type ShellContext = {
  analyticScope: AnalyticShellScope | null
  turnEnsureEnabled: boolean
  turnEnsurePending: boolean
  turnEnsureIsError: boolean
  turnEnsureError: unknown
  turnDataReady: boolean
  turnBlockedNoLogin: boolean
  shellViewpoints: ShellViewpointRow[]
  selectedViewpointName: string | null
  onViewpointChange: (name: string) => void
  shellTurnMax: number | null
  selectedTurn: number | null
  isFutureTurn: boolean
  futureTurnOffset: number
  setTurn: (turn: number) => void
  stepTurn: (delta: number) => void
}

export function useShellContext({ reportShellError }: UseShellContextOptions): ShellContext {
  const loginName = useSessionStore((s) => s.name)
  const credentialsRevision = useSessionStore((s) => s.credentialsRevision)

  const selectedGameId = useShellStore((s) => s.selectedGameId)
  const gameInfoContext = useShellStore((s) => s.gameInfoContext)
  const selectedTurn = useShellStore((s) => s.selectedTurn)
  const perspectiveOverrideName = useShellStore((s) => s.perspectiveOverrideName)
  const storageOnlyLoad = useShellStore((s) => s.storageOnlyLoad)
  const storageAvailablePerspectives = useShellStore((s) => s.storageAvailablePerspectives)
  const setSelectedTurn = useShellStore((s) => s.setSelectedTurn)
  const setPerspectiveOverrideName = useShellStore((s) => s.setPerspectiveOverrideName)
  const setStorageAvailablePerspectives = useShellStore((s) => s.setStorageAvailablePerspectives)

  const shellInputs = useMemo(
    () => ({
      selectedGameId,
      gameInfoContext,
      selectedTurn,
      perspectiveOverrideName,
      loginName,
      storageOnlyLoad,
      storageAvailablePerspectives,
    }),
    [
      selectedGameId,
      gameInfoContext,
      selectedTurn,
      perspectiveOverrideName,
      loginName,
      storageOnlyLoad,
      storageAvailablePerspectives,
    ]
  )

  useEffect(() => {
    if (selectedTurn != null && selectedTurn < 1) {
      setSelectedTurn(1)
    }
  }, [selectedTurn, setSelectedTurn])

  const shellTurnMax = useMemo(
    () => deriveShellTurnMax(gameInfoContext),
    [gameInfoContext]
  )

  const turnView = useMemo(
    () => deriveTurnView(selectedTurn, shellTurnMax),
    [selectedTurn, shellTurnMax]
  )

  const { dataTurn, futureOffset: futureTurnOffset, isFuture: futureTurnActive } = turnView

  const shellViewpoints = useMemo(() => deriveShellViewpoints(shellInputs), [shellInputs])

  const selectedViewpointName = useMemo(
    () => deriveSelectedViewpointName(shellInputs),
    [shellInputs]
  )

  useEffect(() => {
    if (
      shouldClearInProgressPerspectiveOverride(
        gameInfoContext,
        loginName,
        perspectiveOverrideName
      )
    ) {
      setPerspectiveOverrideName(null)
    }
  }, [gameInfoContext, loginName, perspectiveOverrideName, setPerspectiveOverrideName])

  const onViewpointChange = useCallback(
    (name: string) => {
      const perspectives = gameInfoContext?.perspectives ?? []
      if (
        !isViewpointChangeAllowed(
          name,
          gameInfoContext,
          loginName,
          storageOnlyLoad,
          storageAvailablePerspectives,
          perspectives
        )
      ) {
        return
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

  // Lower bound only; no upper clamp -- future turns beyond shellTurnMax are intentional.
  const setTurn = useCallback(
    (absolute: number) => {
      if (shellTurnMax == null) return
      setSelectedTurn(Math.max(1, Math.round(absolute)))
    },
    [shellTurnMax, setSelectedTurn]
  )

  const stepTurn = useCallback(
    (delta: number) => {
      if (shellTurnMax == null || selectedTurn == null) return
      setTurn(selectedTurn + delta)
    },
    [shellTurnMax, selectedTurn, setTurn]
  )

  const analyticScope = useMemo(() => deriveAnalyticScope(shellInputs), [shellInputs])

  const loginTrimmed = loginName?.trim() ?? ''
  const turnEnsureEnabled = deriveTurnEnsureEnabled(analyticScope, loginName, storageOnlyLoad)

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
      credentialsRevision,
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
        password: password || undefined,
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
        reportShellError(
          turnEnsureError instanceof Error
            ? turnEnsureError.message
            : 'Failed to load turn data'
        )
      }
    } else {
      turnEnsureFailureSeen.current = false
    }
  }, [turnEnsureIsError, turnEnsureError, reportShellError])

  const storageTurnResyncSeen = useRef<{ gameId: string; turn: number } | null>(null)
  useEffect(() => {
    if (!storageOnlyLoad || loginTrimmed || !selectedGameId || dataTurn == null) {
      storageTurnResyncSeen.current = null
      return
    }
    const seen = storageTurnResyncSeen.current
    if (seen?.gameId === selectedGameId && seen.turn === dataTurn) {
      return
    }

    let cancelled = false
    const resyncKey = { gameId: selectedGameId, turn: dataTurn }
    void fetchStoredTurnPerspectives(selectedGameId, dataTurn)
      .then(({ perspectives }) => {
        if (cancelled) return
        if (perspectives.length === 0) {
          setStorageAvailablePerspectives([])
          reportShellError(LOGIN_REQUIRED_FOR_GAME_SELECTION)
          return
        }
        setStorageAvailablePerspectives(perspectives)
        const perspectivesRows = useShellStore.getState().gameInfoContext?.perspectives ?? []
        const currentName = useShellStore.getState().perspectiveOverrideName
        const currentOrdinal = perspectiveOrdinalForName(perspectivesRows, currentName)
        if (currentOrdinal != null && perspectives.includes(currentOrdinal)) {
          return
        }
        const nextName = viewpointNameForStoredPerspective(perspectives[0], perspectivesRows)
        if (nextName) {
          setPerspectiveOverrideName(nextName)
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return
        reportShellError(
          err instanceof Error ? err.message : LOGIN_REQUIRED_FOR_GAME_SELECTION
        )
      })
      .finally(() => {
        if (!cancelled) {
          storageTurnResyncSeen.current = resyncKey
        }
      })

    return () => {
      cancelled = true
    }
  }, [
    storageOnlyLoad,
    loginTrimmed,
    selectedGameId,
    dataTurn,
    setStorageAvailablePerspectives,
    setPerspectiveOverrideName,
    reportShellError,
  ])

  const turnBlockedNoLogin = deriveTurnBlockedNoLogin(analyticScope, loginName, storageOnlyLoad)
  const turnDataReady = deriveTurnDataReady(turnEnsureEnabled, turnEnsureSuccess)

  return {
    analyticScope,
    turnEnsureEnabled,
    turnEnsurePending,
    turnEnsureIsError,
    turnEnsureError,
    turnDataReady,
    turnBlockedNoLogin,
    shellViewpoints,
    selectedViewpointName,
    onViewpointChange,
    shellTurnMax,
    selectedTurn,
    isFutureTurn: futureTurnActive,
    futureTurnOffset,
    setTurn,
    stepTurn,
  }
}
