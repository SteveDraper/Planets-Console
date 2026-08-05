import { useEffect } from 'react'
import { useMapAttentionRequestStore } from '../../stores/mapAttentionRequest'
import { useHomeworldLocatorSelectionStore } from '../../stores/homeworldLocatorSelection'

/** Shell fields that invalidate homeworld locator UI selection when any changes. */
export type HomeworldLocatorShellIdentity = {
  gameId: string | null
  turn: number | null
  perspective: number | null
}

/**
 * Clears ephemeral homeworld locator selection and map attention when game, turn,
 * or viewpoint changes. Mount once at the shell level (e.g. ConsoleShell).
 */
export function useClearHomeworldLocatorSelectionOnShellChange(
  identity: HomeworldLocatorShellIdentity
): void {
  const clearSelection = useHomeworldLocatorSelectionStore((s) => s.clearSelection)
  const clearAttention = useMapAttentionRequestStore((s) => s.clearAttention)
  const { gameId, turn, perspective } = identity

  useEffect(() => {
    clearSelection()
    clearAttention()
  }, [gameId, turn, perspective, clearSelection, clearAttention])
}
