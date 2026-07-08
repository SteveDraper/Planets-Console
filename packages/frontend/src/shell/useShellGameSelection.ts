import { useCallback, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  buildGameInfoShellContext,
  getLatestTurnFromGameInfo,
  LOGIN_REQUIRED_FOR_GAME_SELECTION,
  selectableTurnMaxForShell,
} from '../lib/gameInfoShell'
import { loadGameFromStorage, type StorageGameLoadResult } from '../lib/loadGameFromStorage'
import {
  fetchLoadAllTurnsStatus,
  loadAllTurnsWithProgress,
  refreshGameInfo,
  type GameInfoResponse,
  type LoadAllProgressUpdate,
  type LoadAllTurnsResponse,
} from '../api/bff'
import type { GameSelectionOptions } from '../components/GameControl'
import { useSessionStore } from '../stores/session'
import { useShellStore } from '../stores/shell'
import { formatFinalTurnLoadFailuresMessage } from './finalTurnLoadFailuresMessage'
import { invalidateShellGameQueries } from './invalidateShellGameQueries'
import {
  idleLoadAllActivity,
  isLoadAllActivityPending,
  loadAllProgressFromActivity,
  streamingLoadAllActivity,
  type LoadAllActivity,
} from './loadAllActivity'

export type UseShellGameSelectionOptions = {
  reportShellError: (message: string) => void
}

export type LoadAllTurnsVars = {
  gameId: string
  username: string
  password?: string
}

function reportLoadAllFailure(
  result: LoadAllTurnsResponse,
  reportShellError: (message: string) => void
): void {
  const failures = result.final_turn_load_failures ?? []
  if (failures.length === 0) {
    return
  }
  const perspectives = useShellStore.getState().gameInfoContext?.perspectives ?? []
  reportShellError(formatFinalTurnLoadFailuresMessage(failures, perspectives))
}

/** Game refresh, load-all (header or on commit), and a single activity model for the shell. */
export function useShellGameSelection({ reportShellError }: UseShellGameSelectionOptions) {
  const queryClient = useQueryClient()
  const loginName = useSessionStore((s) => s.name)
  const selectedGameId = useShellStore((s) => s.selectedGameId)
  const gameInfoContext = useShellStore((s) => s.gameInfoContext)
  const applyGameInfoRefresh = useShellStore((s) => s.applyGameInfoRefresh)
  const clearStorageOnlyLoad = useShellStore((s) => s.clearStorageOnlyLoad)

  const [loadAllActivity, setLoadAllActivity] = useState<LoadAllActivity>(idleLoadAllActivity)

  const loadAllTurnsMutation = useMutation({
    mutationFn: async (vars: LoadAllTurnsVars): Promise<LoadAllTurnsResponse> => {
      setLoadAllActivity(streamingLoadAllActivity())
      try {
        const result = await loadAllTurnsWithProgress(
          vars.gameId,
          { username: vars.username, password: vars.password },
          (progress: LoadAllProgressUpdate) => {
            setLoadAllActivity({ phase: 'streaming', progress })
          }
        )
        reportLoadAllFailure(result, reportShellError)
        return result
      } finally {
        setLoadAllActivity(idleLoadAllActivity)
      }
    },
    retry: false,
    onSuccess: (_data, vars) => {
      clearStorageOnlyLoad()
      invalidateShellGameQueries(queryClient, vars.gameId)
    },
    onError: (err) => {
      const message =
        err instanceof Error
          ? err.message
          : typeof err === 'string'
            ? err
            : 'Load all turns failed'
      reportShellError(message)
    },
  })

  const executeLoadAllTurns = useCallback(
    (vars: LoadAllTurnsVars) => loadAllTurnsMutation.mutateAsync(vars),
    [loadAllTurnsMutation]
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
          await executeLoadAllTurns({
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
            perspectiveOverrideOrdinal: load.defaultViewpointOrdinal,
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

      invalidateShellGameQueries(queryClient, vars.gameId)
    },
    onError: (err) => {
      const message =
        err instanceof Error ? err.message : typeof err === 'string' ? err : 'Game refresh failed'
      reportShellError(message)
    },
    onSettled: () => {
      setLoadAllActivity((current) =>
        current.phase === 'awaiting-refresh' ? idleLoadAllActivity : current
      )
    },
  })

  const { data: loadAllTurnsStatus } = useQuery({
    queryKey: ['bff', 'games', selectedGameId, 'load-all-status', loginName?.trim() ?? ''],
    queryFn: () => fetchLoadAllTurnsStatus(selectedGameId!, loginName!.trim()),
    enabled: Boolean(selectedGameId && loginName?.trim() && gameInfoContext != null),
    staleTime: 30_000,
  })

  const handleCommitGameSelection = useCallback(
    (gameId: string, options?: GameSelectionOptions) => {
      const { name, password } = useSessionStore.getState()
      if (options?.loadAllTurns) {
        setLoadAllActivity({ phase: 'awaiting-refresh' })
      }
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
      reportShellError(LOGIN_REQUIRED_FOR_GAME_SELECTION)
      return
    }
    loadAllTurnsMutation.mutate({
      gameId: selectedGameId,
      username,
      password: password || undefined,
    })
  }, [selectedGameId, loadAllTurnsMutation, reportShellError])

  const isLoadAllTurnsDisabled =
    !loginName?.trim() ||
    loadAllTurnsStatus?.complete === true ||
    gameInfoContext == null

  const loadAllProgress = loadAllProgressFromActivity(loadAllActivity)
  const isLoadAllTurnsPending = isLoadAllActivityPending(loadAllActivity)

  return {
    loadAllProgress,
    loadAllTurnsStatus,
    handleCommitGameSelection,
    handleLoadAllTurns,
    isGameRefreshPending: refreshGameMutation.isPending,
    isLoadAllTurnsDisabled,
    isLoadAllTurnsPending,
  }
}
