import { useEffect } from 'react'
import { useMapAttentionRequestStore } from '../../stores/mapAttentionRequest'

/** Shell fields that invalidate homeworld locator map attention when any changes. */
export type HomeworldLocatorShellIdentity = {
  gameId: string | null
  turn: number | null
  perspective: number | null
}

/**
 * Clears ephemeral homeworld locator map attention when game, turn, or viewpoint
 * changes. Mount once at the shell level (e.g. ConsoleShell).
 */
export function useClearHomeworldLocatorAttentionOnShellChange(
  identity: HomeworldLocatorShellIdentity
): void {
  const clearAttention = useMapAttentionRequestStore((s) => s.clearAttention)
  const { gameId, turn, perspective } = identity

  useEffect(() => {
    clearAttention()
  }, [gameId, turn, perspective, clearAttention])
}
