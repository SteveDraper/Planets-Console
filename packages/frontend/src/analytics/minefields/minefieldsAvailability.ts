import type { GameInfoResponse } from '../../api/bff'

export const INACTIVE_REASON_NO_MINEFIELDS = 'nominefields'

export const MINEFIELDS_INACTIVE_HINT = 'This game has no minefields'

/**
 * Mirror GameSettings.nominefields from GameInfo so the sidebar can grey
 * before the analytic is enabled.
 */
export function minefieldsInactiveReasonFromGameInfo(
  data: GameInfoResponse | null | undefined
): string | null {
  if (data == null) return null
  for (const block of [data.settings, data.game]) {
    if (block == null || typeof block !== 'object' || Array.isArray(block)) continue
    const rec = block as Record<string, unknown>
    if (rec.nominefields === true) {
      return INACTIVE_REASON_NO_MINEFIELDS
    }
  }
  return null
}

export function minefieldsInactiveHint(reason: string | null | undefined): string {
  if (reason === INACTIVE_REASON_NO_MINEFIELDS || reason == null || reason === '') {
    return MINEFIELDS_INACTIVE_HINT
  }
  return `Minefields unavailable (${reason})`
}
