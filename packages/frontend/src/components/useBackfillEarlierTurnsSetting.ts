import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchBackfillEarlierTurns, putBackfillEarlierTurns } from '../api/bff'
import { errorDetailFromUnknown } from '../lib/queryRetry'

export function backfillEarlierTurnsQueryKey(gameId: string) {
  return ['backfillEarlierTurns', gameId] as const
}

export function useBackfillEarlierTurnsSetting(gameId: string | null) {
  const queryClient = useQueryClient()
  const hasGame = gameId != null && gameId !== ''
  const query = useQuery({
    queryKey: backfillEarlierTurnsQueryKey(hasGame ? gameId : ''),
    queryFn: () => fetchBackfillEarlierTurns(gameId ?? ''),
    enabled: hasGame,
  })
  const mutation = useMutation({
    mutationFn: async (enabled: boolean) => {
      if (!hasGame || gameId == null) {
        throw new Error('Select a game first.')
      }
      const body = await putBackfillEarlierTurns(gameId, enabled)
      queryClient.setQueryData(backfillEarlierTurnsQueryKey(gameId), body)
      return body
    },
  })

  const isOn = mutation.isPending
    ? mutation.variables === true
    : (query.data?.backfillEarlierTurns ?? false)
  const error = query.isError
    ? errorDetailFromUnknown(query.error)
    : mutation.isError
      ? errorDetailFromUnknown(mutation.error)
      : null

  return {
    isOn,
    canEdit: hasGame && query.isSuccess && !mutation.isPending,
    error,
    setOn: (enabled: boolean) => {
      if (!hasGame || mutation.isPending) return
      mutation.mutate(enabled)
    },
  }
}
