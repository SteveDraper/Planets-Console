/** Visibility region kind ids (match Core ``visibility_coverage`` wire kinds). */

export const VISIBILITY_REGION_KINDS = [
  'ship-scan',
  'active-sensor-sweep',
  'potential-sensor-sweep',
  'active-minefield-detect',
  'potential-minefield-detect',
] as const

export type VisibilityRegionKind = (typeof VISIBILITY_REGION_KINDS)[number]

export type VisibilityKindPreference = {
  enabled: boolean
  fillColor: string
}

export type VisibilityKindPreferences = Record<VisibilityRegionKind, VisibilityKindPreference>

export const VISIBILITY_KIND_LABELS: Record<VisibilityRegionKind, string> = {
  'ship-scan': 'Ship scan',
  'active-sensor-sweep': 'Active Sensor Sweep',
  'potential-sensor-sweep': 'Potential Sensor Sweep',
  'active-minefield-detect': 'Active minefield detect',
  'potential-minefield-detect': 'Potential minefield detect',
}

/** Wire / fresh-install default base colors (distinct per kind). */
export const DEFAULT_VISIBILITY_KIND_COLORS: Record<VisibilityRegionKind, string> = {
  'ship-scan': '#38bdf8',
  'active-sensor-sweep': '#a78bfa',
  'potential-sensor-sweep': '#fbbf24',
  'active-minefield-detect': '#34d399',
  'potential-minefield-detect': '#fb7185',
}

export function defaultVisibilityKindPreferences(): VisibilityKindPreferences {
  return {
    'ship-scan': { enabled: true, fillColor: DEFAULT_VISIBILITY_KIND_COLORS['ship-scan'] },
    'active-sensor-sweep': {
      enabled: true,
      fillColor: DEFAULT_VISIBILITY_KIND_COLORS['active-sensor-sweep'],
    },
    'potential-sensor-sweep': {
      enabled: true,
      fillColor: DEFAULT_VISIBILITY_KIND_COLORS['potential-sensor-sweep'],
    },
    'active-minefield-detect': {
      enabled: true,
      fillColor: DEFAULT_VISIBILITY_KIND_COLORS['active-minefield-detect'],
    },
    'potential-minefield-detect': {
      enabled: true,
      fillColor: DEFAULT_VISIBILITY_KIND_COLORS['potential-minefield-detect'],
    },
  }
}

export function isVisibilityRegionKind(kind: string): kind is VisibilityRegionKind {
  return (VISIBILITY_REGION_KINDS as readonly string[]).includes(kind)
}

export const VISIBILITY_EXCLUSIONS_HELP =
  'Ship-scan and Sensor Sweep use nebula V(P) (plus Nebula Scanner floors). Minefield detect disks are not nebula-modulated. Coverage ignores cloak, Stealth Armor, Hide in Warp Well, and special detection abilities. Industry/defense-post and ion-storm gates affect reports inside regions, not disk shape.'
