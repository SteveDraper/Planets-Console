import { useCallback, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchLoadAllTurnsStatus,
  loadAllTurnsWithProgress,
  type LoadAllProgressUpdate,
} from '../api/bff'
import { LOGIN_REQUIRED_FOR_GAME_SELECTION } from '../lib/gameInfoShell'
import { useSessionStore } from '../stores/session'
import { useShellStore } from '../stores/shell'
import { formatFinalTurnLoadFailuresMessage } from './finalTurnLoadFailuresMessage'

export type UseLoadAllTurnsOptions = {
  reportShellError: (message: string) => void
}

export function useLoadAllTurns({ reportShellError }: UseLoadAllTurnsOptions) {
  const queryClient = useQueryClient()
  const loginName = useSessionStore((s) => s.name)
  const selectedGameId = useShellStore((s) => s.selectedGameId)
  const gameInfoContext = useShellStore((s) => s.gameInfoContext)
  const clearStorageOnlyLoad = useShellStore((s) => s.clearStorageOnlyLoad)

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
        const result = await loadAllTurnsWithProgress(
          vars.gameId,
          { username: vars.username, password: vars.password },
          setLoadAllProgress
        )
        const failures = result.final_turn_load_failures
        if (failures != null && failures.length > 0) {
          const perspectives =
            useShellStore.getState().gameInfoContext?.perspectives ?? []
          reportShellError(
            formatFinalTurnLoadFailuresMessage(failures, perspectives)
          )
        }
        return result
      } finally {
        setLoadAllProgress(null)
      }
    },
    [reportShellError]
  )

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
      reportShellError(message)
    },
  })

  const { data: loadAllTurnsStatus } = useQuery({
    queryKey: ['bff', 'games', selectedGameId, 'load-all-status', loginName?.trim() ?? ''],
    queryFn: () => fetchLoadAllTurnsStatus(selectedGameId!, loginName!.trim()),
    enabled: Boolean(selectedGameId && loginName?.trim() && gameInfoContext != null),
    staleTime: 30_000,
  })

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

  const isLoadAllTurnsPending =
    loadAllProgress != null || loadAllTurnsMutation.isPending

  return {
    loadAllProgress,
    runLoadAllTurns,
    loadAllTurnsMutation,
    loadAllTurnsStatus,
    isLoadAllTurnsDisabled,
    isLoadAllTurnsPending,
    handleLoadAllTurns,
  }
}
