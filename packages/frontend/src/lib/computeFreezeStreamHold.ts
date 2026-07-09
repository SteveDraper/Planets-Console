import type { AnalyticShellScope } from '../api/bff'
import type { ComputeDiagnosticsSnapshot } from '../stores/computeDiagnostics'
import { analyticScopeKey } from './analyticScopeKey'

export type ComputeFreezeStreamHold = {
  /** Freeze is armed for this shell; server narrows stream subscriptions to the allowlist. */
  holding: boolean
  /**
   * Players the stream is expected to complete while holding.
   * Empty set means subscribe to none and stay pending (do not treat as failure).
   * Null when not holding -- all requested players are expected.
   */
  expectedPlayerIds: ReadonlySet<number> | null
}

function sameGameId(
  left: AnalyticShellScope['gameId'],
  right: AnalyticShellScope['gameId']
): boolean {
  return String(left) === String(right)
}

export function computeFreezeStreamHold(
  scope: AnalyticShellScope,
  state: {
    enabled: boolean
    snapshot: ComputeDiagnosticsSnapshot | null
  }
): ComputeFreezeStreamHold {
  if (!state.enabled || state.snapshot == null || !state.snapshot.freezeArmed) {
    return { holding: false, expectedPlayerIds: null }
  }
  // Sticky freeze is per-game; disarm on game change (server clears freeze).
  if (!sameGameId(state.snapshot.shell.gameId, scope.gameId)) {
    return { holding: false, expectedPlayerIds: null }
  }
  // Same full shell: use the snapshot allowlist.
  if (analyticScopeKey(state.snapshot.shell) === analyticScopeKey(scope)) {
    return {
      holding: true,
      expectedPlayerIds: new Set(state.snapshot.allowlistedPlayerIds),
    }
  }
  // Same game, different turn/perspective: allowlist resets empty on the server
  // until a fresh snapshot for the new shell arrives. Hold with no subscriptions.
  return {
    holding: true,
    expectedPlayerIds: new Set(),
  }
}

/**
 * Players the client should subscribe to / wait on for stream completion.
 * Under freeze, only the allowlist intersection; empty allowlist → no subscription.
 */
export function streamSubscriptionPlayerIds(
  playerIds: readonly number[],
  hold: ComputeFreezeStreamHold
): number[] {
  if (!hold.holding || hold.expectedPlayerIds == null) {
    return [...playerIds]
  }
  return playerIds.filter((playerId) => hold.expectedPlayerIds!.has(playerId))
}

export function hasPendingPlayersForStream(
  playerIds: readonly number[],
  isPlayerComplete: (playerId: number) => boolean,
  hold: ComputeFreezeStreamHold
): boolean {
  const subscribed = streamSubscriptionPlayerIds(playerIds, hold)
  // Freeze + empty allowlist: nothing is subscribed; stay pending without retries.
  // Callers treat "no subscribed players while holding" as held (not incomplete).
  if (hold.holding && subscribed.length === 0) {
    return false
  }
  return subscribed.some((playerId) => !isPlayerComplete(playerId))
}

export function freezeStreamHoldKey(hold: ComputeFreezeStreamHold): string {
  if (!hold.holding || hold.expectedPlayerIds == null) {
    return ''
  }
  const ids = [...hold.expectedPlayerIds].sort((left, right) => left - right).join(',')
  return `freeze:${ids}`
}
