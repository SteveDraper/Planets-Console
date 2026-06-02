import type { QueryClient } from '@tanstack/react-query'

/** Invalidate games list and per-game load-all status after refresh or bulk load. */
export function invalidateShellGameQueries(
  queryClient: QueryClient,
  gameId: string
): void {
  void queryClient.invalidateQueries({ queryKey: ['bff', 'games'] })
  void queryClient.invalidateQueries({
    queryKey: ['bff', 'games', gameId, 'load-all-status'],
  })
}
