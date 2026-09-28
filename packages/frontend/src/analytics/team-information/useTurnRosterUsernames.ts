import { useSyncExternalStore } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { AnalyticShellScope } from '../../api/bff'
import { useSessionStore } from '../../stores/session'

type TurnEnsureCache = {
  turnUsernamesByPlayerId: ReadonlyMap<number, string>
}

/**
 * Read usernames already cached by the shell turn-ensure query.
 * Does not register a second observer, so it cannot replace that query's fetch.
 */
export function useTurnRosterUsernames(
  analyticScope: AnalyticShellScope | null
): ReadonlyMap<number, string> | null {
  const queryClient = useQueryClient()
  const loginTrimmed = useSessionStore((s) => s.name)?.trim() ?? ''
  const credentialsRevision = useSessionStore((s) => s.credentialsRevision)
  const queryKey = [
    'bff',
    'turnData',
    analyticScope?.gameId ?? '',
    analyticScope?.turn ?? 0,
    analyticScope?.perspective ?? 0,
    loginTrimmed,
    credentialsRevision,
  ] as const

  return useSyncExternalStore(
    (onStoreChange) => queryClient.getQueryCache().subscribe(onStoreChange),
    () => queryClient.getQueryData<TurnEnsureCache>(queryKey)?.turnUsernamesByPlayerId ?? null
  )
}
