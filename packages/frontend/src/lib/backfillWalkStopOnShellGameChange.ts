import { useShellStore } from '../stores/shell'
import { requestBackfillWalkStop } from './backfillWalkStop'

/**
 * Stop the walks of the game the shell leaves (G to another game or to null). The shell store
 * starts with no game, so its initial load and persist hydration never leave one.
 */
export function installBackfillWalkStopOnShellGameChange(): () => void {
  return useShellStore.subscribe((state, previousState) => {
    const leftGameId = previousState.selectedGameId
    if (leftGameId != null && state.selectedGameId !== leftGameId) {
      void requestBackfillWalkStop(leftGameId)
    }
  })
}
