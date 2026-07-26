import type { GameInfoResponse } from '../../api/bff'
import {
  HOMEWORLD_LOCATOR_ANALYTIC_ID,
  INACTIVE_REASON_NO_HOMEWORLD,
  INACTIVE_REASON_SCENARIO_OVERRIDE,
  INACTIVE_REASON_WANDERING_TRIBES,
} from './constants'

/** Mirror of Core ``HW_DISTRIBUTION_ONE_VS_CIRCLE`` (Ashes recipe signal). */
const HW_DISTRIBUTION_ONE_VS_CIRCLE = 4

/**
 * Mirror Core ``homeworld_locator_inactive_reason`` from GameInfo settings.
 * Catalog greying uses this so the sidebar can hint before the analytic is enabled.
 *
 * Scenario recipes have no name field -- detect Ashes via ``hwdistribution === 4``,
 * Crazy Intermix / Disunited Kingdoms via ``extraplanets > 0``.
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
    const hwdistribution = rec.hwdistribution
    if (
      typeof hwdistribution === 'number' &&
      Number.isFinite(hwdistribution) &&
      hwdistribution === HW_DISTRIBUTION_ONE_VS_CIRCLE
    ) {
      return INACTIVE_REASON_SCENARIO_OVERRIDE
    }
    const extraplanets = rec.extraplanets
    if (typeof extraplanets === 'number' && Number.isFinite(extraplanets) && extraplanets > 0) {
      return INACTIVE_REASON_SCENARIO_OVERRIDE
    }
  }
  return null
}

export function isHomeworldLocatorAvailableFromGameInfo(
  data: GameInfoResponse | null | undefined
): boolean {
  return homeworldLocatorInactiveReasonFromGameInfo(data) == null
}

/**
 * Drop homeworld-locator from the effective enabled list when GameInfo marks it inactive.
 * Persisted store enablement is left intact so it can restore when the game becomes available.
 */
export function withoutInactiveHomeworldLocator(
  enabledAnalyticIds: readonly string[],
  inactiveReason: string | null
): string[] {
  if (inactiveReason == null) {
    return [...enabledAnalyticIds]
  }
  return enabledAnalyticIds.filter((id) => id !== HOMEWORLD_LOCATOR_ANALYTIC_ID)
}
