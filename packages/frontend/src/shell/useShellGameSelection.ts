import { useCallback } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  buildGameInfoShellContext,
  getLatestTurnFromGameInfo,
  selectableTurnMaxForShell,
} from '../lib/gameInfoShell'
import { loadGameFromStorage, type StorageGameLoadResult } from '../lib/loadGameFromStorage'
import { refreshGameInfo, type GameInfoResponse } from '../api/bff'
import type { GameSelectionOptions } from '../components/GameControl'
import { useSessionStore } from '../stores/session'
import { useShellStore } from '../stores/shell'
import { useLoadAllTurns, type UseLoadAllTurnsOptions } from './useLoadAllTurns'

export type UseShellGameSelectionOptions = UseLoadAllTurnsOptions

/** Game refresh, optional load-all on commit, and unified load-all pending state for the shell. */
export function useShellGameSelection({ reportShellError }: UseShellGameSelectionOptions) {
  const queryClient = useQueryClient()
  const applyGameInfoRefresh = useShellStore((s) => s.applyGameInfoRefresh)
  const clearStorageOnlyLoad = useShellStore((s) => s.clearStorageOnlyLoad)

  const loadAll = useLoadAllTurns({ reportShellError })

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
          await loadAll.runLoadAllTurns({
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
      reportShellError(message)
    },
  })

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

  const isLoadAllTurnsPending =
    loadAll.isLoadAllTurnsPending ||
    (refreshGameMutation.isPending && refreshGameMutation.variables?.loadAllTurns === true)

  return {
    ...loadAll,
    refreshGameMutation,
    handleCommitGameSelection,
    isGameRefreshPending: refreshGameMutation.isPending,
    isLoadAllTurnsPending,
  }
}
