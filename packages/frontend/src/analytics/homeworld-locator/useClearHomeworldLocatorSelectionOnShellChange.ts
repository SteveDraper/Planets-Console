import { useEffect } from 'react'
import { useHomeworldCandidateFlashStore } from '../../stores/homeworldCandidateFlash'
import { useHomeworldLocatorSelectionStore } from '../../stores/homeworldLocatorSelection'

/** Shell fields that invalidate homeworld locator UI selection when any changes. */
export type HomeworldLocatorShellIdentity = {
  gameId: string | null
  turn: number | null
  perspective: number | null
}

/**
 * Clears ephemeral homeworld locator selection and candidate flash when game, turn,
 * or viewpoint changes. Mount once at the shell level (e.g. ConsoleShell).
 */
export function useClearHomeworldLocatorSelectionOnShellChange(
  identity: HomeworldLocatorShellIdentity
): void {
  const clearSelection = useHomeworldLocatorSelectionStore((s) => s.clearSelection)
  const clearFlash = useHomeworldCandidateFlashStore((s) => s.clearFlash)
  const { gameId, turn, perspective } = identity

  useEffect(() => {
    clearSelection()
    clearFlash()
  }, [gameId, turn, perspective, clearSelection, clearFlash])
}
