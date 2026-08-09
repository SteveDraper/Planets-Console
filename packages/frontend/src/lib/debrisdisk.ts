/**
 * Host ``debrisdisk`` coercion shared across analytics (homeworld planetoid checks, etc.).
 * Matches Core ``planet.debrisdisk`` number semantics after wire number/string normalize.
 */

/** Coerce host ``debrisdisk`` (number or numeric string) to a finite number, else null. */
export function debrisdiskValue(raw: unknown): number | null {
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw
  if (typeof raw === 'string' && raw.trim() !== '') {
    const parsed = Number(raw)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

/**
 * Non-zero ``debrisdisk`` means the body is in a debris disk (no warp wells for map geometry).
 * Matches Core ``planet_is_in_debris_disk`` after coerce.
 */
export function planetIsInDebrisDisk(raw: unknown): boolean {
  const value = debrisdiskValue(raw)
  return value != null && value !== 0
}
