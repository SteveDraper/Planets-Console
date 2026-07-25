/** Canonical id for the Homeworld locator turn analytic. */
export const HOMEWORLD_LOCATOR_ANALYTIC_ID = 'homeworld-locator'

export const CONFIDENCE_DEFINITE = 'definite' as const
export const CONFIDENCE_POSSIBLE = 'possible' as const

export const INACTIVE_REASON_NO_HOMEWORLD = 'nohomeworld'
export const INACTIVE_REASON_WANDERING_TRIBES = 'wandering_tribes'

export const HOMEWORLD_INACTIVE_HINTS: Record<string, string> = {
  [INACTIVE_REASON_NO_HOMEWORLD]: 'This game has no homeworld planets',
  [INACTIVE_REASON_WANDERING_TRIBES]:
    'Wandering Tribes games start in fleets, not on homeworld planets',
}

export function homeworldInactiveHint(reason: string | null | undefined): string {
  if (reason == null || reason === '') {
    return 'Homeworld locator is unavailable for this game'
  }
  return HOMEWORLD_INACTIVE_HINTS[reason] ?? `Homeworld locator unavailable (${reason})`
}
