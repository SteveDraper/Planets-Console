/** Minefield type ids painted independently in the Minefields analytic. */

export const MINEFIELD_TYPE_IDS = ['normal', 'web'] as const

export type MinefieldTypeId = (typeof MINEFIELD_TYPE_IDS)[number]

export const MINEFIELD_PAINT_POLICIES = ['owner', 'stance'] as const

export type MinefieldPaintPolicy = (typeof MINEFIELD_PAINT_POLICIES)[number]

export const MINEFIELD_PAINT_POLICY_LABELS: Record<MinefieldPaintPolicy, string> = {
  owner: 'Owner',
  stance: 'Stance',
}

export const MINEFIELD_TYPE_LABELS: Record<MinefieldTypeId, string> = {
  normal: 'Normal',
  web: 'Web',
}

/** Stance in-circle / out-of-circle defaults (ticket #288). */
export const DEFAULT_MINEFIELD_STANCE_COLORS = {
  normal: { in: '#34d399', out: '#fb7185' },
  web: { in: '#8480d4', out: '#a78bfa' },
} as const

export const INTERIOR_FILL_OPACITY = 0.22
export const ANNULUS_FILL_OPACITY = 0.1
export const STALE_FILL_OPACITY_FACTOR = 0.55
export const STROKE_OPACITY = 0.9

export function minefieldTypeId(isWeb: boolean): MinefieldTypeId {
  return isWeb ? 'web' : 'normal'
}
