import { postBackfillWalksStop } from '../api/backfillWalksClient'
import { useShellStore } from '../stores/shell'

/**
 * Client-only, in-memory: the chained stop promise per game id the shell left. An entry exists
 * only while its chain is unsettled, and every chain resolves (a failed stop is logged), so a
 * stream that awaits it before re-entering the game is never blocked indefinitely.
 */
const pendingStopsByGameId = new Map<string, Promise<void>>()

/** Queue a stop for `gameId` after any stop already pending for it. */
export function requestBackfillWalkStop(gameId: string): Promise<void> {
  const previousStop = pendingStopsByGameId.get(gameId) ?? Promise.resolve()
  const chainedStop: Promise<void> = previousStop
    .then(() => postBackfillWalksStop(gameId))
    .catch((error: unknown) => {
      console.warn(`Backfill walk stop failed for game ${gameId}`, error)
    })
    .finally(() => {
      if (pendingStopsByGameId.get(gameId) === chainedStop) {
        pendingStopsByGameId.delete(gameId)
      }
    })
  pendingStopsByGameId.set(gameId, chainedStop)
  return chainedStop
}

/** The unsettled stop chain for `gameId`, or undefined when none is pending. */
export function pendingBackfillWalkStop(gameId: string): Promise<void> | undefined {
  return pendingStopsByGameId.get(gameId)
}

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
