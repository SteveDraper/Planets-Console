/** Canonical id for the Homeworld locator turn analytic. */
export const HOMEWORLD_LOCATOR_ANALYTIC_ID = 'homeworld-locator'

export const CONFIDENCE_DEFINITE = 'definite' as const
export const CONFIDENCE_POSSIBLE = 'possible' as const

/** Ownership / location provenance kind minted by UI asserts (Core ``PROVENANCE_ASSERTED``). */
export const PROVENANCE_KIND_ASSERTED = 'asserted' as const

export const INACTIVE_REASON_NO_HOMEWORLD = 'nohomeworld'
export const INACTIVE_REASON_WANDERING_TRIBES = 'wandering_tribes'
/** Ashes / Crazy Intermix / Disunited Kingdoms (recipe-shaped GameSettings). */
export const INACTIVE_REASON_SCENARIO_OVERRIDE = 'scenario_override'

export const HOMEWORLD_INACTIVE_HINTS: Record<string, string> = {
  [INACTIVE_REASON_NO_HOMEWORLD]: 'This game has no homeworld planets',
  [INACTIVE_REASON_WANDERING_TRIBES]:
    'Wandering Tribes games start in fleets, not on homeworld planets',
  [INACTIVE_REASON_SCENARIO_OVERRIDE]:
    'Scenario recipes (Ashes, Crazy Intermix, Disunited Kingdoms) use a nontraditional homeworld setup',
}

export function homeworldInactiveHint(reason: string | null | undefined): string {
  if (reason == null || reason === '') {
    return 'Homeworld locator is unavailable for this game'
  }
  return HOMEWORLD_INACTIVE_HINTS[reason] ?? `Homeworld locator unavailable (${reason})`
}

/** Shared table/map copy when baseline used a turn later than 1. */
export function homeworldBaselineDegradedMessage(
  baselineTurn: number | null | undefined
): string {
  const turnClause =
    baselineTurn != null ? ` (using turn ${baselineTurn}; turn 1 not available)` : ''
  return `Baseline degraded${turnClause}. Definite matches are applied cautiously.`
}
