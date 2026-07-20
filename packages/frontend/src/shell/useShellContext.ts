import { useCallback, useEffect, useMemo, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ensureTurnData,
  fetchStoredTurnPerspectives,
  type AnalyticShellScope,
} from '../api/bff'
import { LOGIN_REQUIRED_FOR_GAME_SELECTION } from '../lib/gameInfoShell'
import { useSessionStore } from '../stores/session'
import { useShellStore } from '../stores/shell'
import {
  deriveAnalyticScope,
  deriveSelectedViewpointOrdinal,
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
  selectedViewpointOrdinal: number | null
  onViewpointChange: (ordinal: number) => void
  shellTurnMax: number | null
  selectedTurn: number | null
  isFuture: boolean
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
  const perspectiveOverrideOrdinal = useShellStore((s) => s.perspectiveOverrideOrdinal)
  const storageOnlyLoad = useShellStore((s) => s.storageOnlyLoad)
  const storageAvailablePerspectives = useShellStore((s) => s.storageAvailablePerspectives)
  const setSelectedTurn = useShellStore((s) => s.setSelectedTurn)
  const setPerspectiveOverrideOrdinal = useShellStore((s) => s.setPerspectiveOverrideOrdinal)
  const setStorageAvailablePerspectives = useShellStore((s) => s.setStorageAvailablePerspectives)

  const shellTurnMax = useMemo(
    () => deriveShellTurnMax(gameInfoContext),
    [gameInfoContext]
  )

  const turnView = useMemo(
    () => deriveTurnView(selectedTurn, shellTurnMax),
    [selectedTurn, shellTurnMax]
  )

  const { dataTurn, futureOffset: futureTurnOffset, isFuture } = turnView

  const scopeInputs = useMemo(
    () => ({
      selectedGameId,
      gameInfoContext,
      selectedTurn,
      perspectiveOverrideOrdinal,
      loginName,
      storageOnlyLoad,
      storageAvailablePerspectives,
      viewedDataTurn: dataTurn,
      turnUsernamesByPlayerId: null as ReadonlyMap<number, string> | null,
    }),
    [
      selectedGameId,
      gameInfoContext,
      selectedTurn,
      perspectiveOverrideOrdinal,
      loginName,
      storageOnlyLoad,
      storageAvailablePerspectives,
      dataTurn,
    ]
  )

  const analyticScopeForEnsure = useMemo(
    () => deriveAnalyticScope(scopeInputs),
    [scopeInputs]
  )

  const loginTrimmed = loginName?.trim() ?? ''
  const turnEnsureEnabled = deriveTurnEnsureEnabled(
    analyticScopeForEnsure,
    loginName,
    storageOnlyLoad
  )

  const {
    data: turnEnsureData,
    isSuccess: turnEnsureSuccess,
    isPending: turnEnsurePending,
    isError: turnEnsureIsError,
    error: turnEnsureError,
  } = useQuery({
    queryKey: [
      'bff',
      'turnData',
      analyticScopeForEnsure?.gameId ?? '',
      analyticScopeForEnsure?.turn ?? 0,
      analyticScopeForEnsure?.perspective ?? 0,
      loginTrimmed,
      credentialsRevision,
    ] as const,
    queryFn: () => {
      const { name } = useSessionStore.getState()
      const user = name?.trim() ?? ''
      if (!analyticScopeForEnsure) {
        throw new Error('Missing shell scope')
      }
      return ensureTurnData(analyticScopeForEnsure.gameId, {
        turn: analyticScopeForEnsure.turn,
        perspective: analyticScopeForEnsure.perspective,
        username: user,
      })
    },
    enabled: turnEnsureEnabled,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })

  const turnUsernamesByPlayerId = turnEnsureData?.turnUsernamesByPlayerId ?? null

  const shellInputs = useMemo(
    () => ({
      selectedGameId,
      gameInfoContext,
      selectedTurn,
      perspectiveOverrideOrdinal,
      loginName,
      storageOnlyLoad,
      storageAvailablePerspectives,
      viewedDataTurn: dataTurn,
      turnUsernamesByPlayerId,
    }),
    [
      selectedGameId,
      gameInfoContext,
      selectedTurn,
      perspectiveOverrideOrdinal,
      loginName,
      storageOnlyLoad,
      storageAvailablePerspectives,
      dataTurn,
      turnUsernamesByPlayerId,
    ]
  )

  useEffect(() => {
    if (selectedTurn != null && selectedTurn < 1) {
      setSelectedTurn(1)
    }
  }, [selectedTurn, setSelectedTurn])

  const shellViewpoints = useMemo(() => deriveShellViewpoints(shellInputs), [shellInputs])

  const selectedViewpointOrdinal = useMemo(
    () => deriveSelectedViewpointOrdinal(shellInputs),
    [shellInputs]
  )

  useEffect(() => {
    if (
      shouldClearInProgressPerspectiveOverride(
        gameInfoContext,
        loginName,
        perspectiveOverrideOrdinal
      )
    ) {
      setPerspectiveOverrideOrdinal(null)
    }
  }, [
    gameInfoContext,
    loginName,
    perspectiveOverrideOrdinal,
    setPerspectiveOverrideOrdinal,
  ])

  const onViewpointChange = useCallback(
    (ordinal: number) => {
      if (
        !isViewpointChangeAllowed(
          ordinal,
          gameInfoContext,
          loginName,
          storageOnlyLoad,
          storageAvailablePerspectives
        )
      ) {
        return
      }
      setPerspectiveOverrideOrdinal(ordinal)
    },
    [
      gameInfoContext,
      loginName,
      setPerspectiveOverrideOrdinal,
      storageOnlyLoad,
      storageAvailablePerspectives,
    ]
  )

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
        const currentOrdinal = useShellStore.getState().perspectiveOverrideOrdinal
        if (currentOrdinal != null && perspectives.includes(currentOrdinal)) {
          return
        }
        const nextOrdinal = perspectives[0]
        if (nextOrdinal != null) {
          setPerspectiveOverrideOrdinal(nextOrdinal)
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
    setPerspectiveOverrideOrdinal,
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
    selectedViewpointOrdinal,
    onViewpointChange,
    shellTurnMax,
    selectedTurn,
    isFuture,
    futureTurnOffset,
    setTurn,
    stepTurn,
  }
}
