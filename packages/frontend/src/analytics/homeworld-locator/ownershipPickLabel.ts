/**
 * Ownership assert pick-list label: ``"<name> (<race>)"`` → slot id on submit.
 * Race is display-only; Core persists ``ownerSlot`` only (ADR 0010).
 */

export function formatHomeworldOwnershipPickLabel(
  name: string,
  raceName: string | null | undefined
): string {
  const trimmedName = name.trim() || 'Player'
  const race = raceName?.trim() ?? ''
  if (race === '') return trimmedName
  return `${trimmedName} (${race})`
}
