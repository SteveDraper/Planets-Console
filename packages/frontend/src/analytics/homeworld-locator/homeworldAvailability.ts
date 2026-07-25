import type { GameInfoResponse } from '../../api/bff'
import {
  INACTIVE_REASON_NO_HOMEWORLD,
  INACTIVE_REASON_WANDERING_TRIBES,
} from './constants'

/**
 * Mirror Core ``homeworld_locator_inactive_reason`` from GameInfo settings.
 * Catalog greying uses this so the sidebar can hint before the analytic is enabled.
 */
export function homeworldLocatorInactiveReasonFromGameInfo(
  data: GameInfoResponse | null | undefined
): string | null {
  if (data == null) return null
  for (const block of [data.settings, data.game]) {
    if (block == null || typeof block !== 'object' || Array.isArray(block)) continue
    const rec = block as Record<string, unknown>
    if (rec.nohomeworld === true) {
      return INACTIVE_REASON_NO_HOMEWORLD
    }
    const wandering = rec.wanderingtribescount
    if (typeof wandering === 'number' && Number.isFinite(wandering) && wandering > 0) {
      return INACTIVE_REASON_WANDERING_TRIBES
    }
  }
  return null
}

export function isHomeworldLocatorAvailableFromGameInfo(
  data: GameInfoResponse | null | undefined
): boolean {
  return homeworldLocatorInactiveReasonFromGameInfo(data) == null
}
