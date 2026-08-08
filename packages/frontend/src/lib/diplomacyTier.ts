/**
 * Planets.nu Relation.relationto / relationfrom ladder.
 * Mirrors Core ``api.concepts.diplomacy.DiplomacyTier``.
 */
export const DiplomacyTier = {
  BLOCKED: -1,
  NONE: 0,
  AMBASSADOR: 1,
  SAFE_PASSAGE: 2,
  SHARE_INTEL: 3,
  FULL_ALLIANCE: 4,
} as const

export type DiplomacyTierCode = (typeof DiplomacyTier)[keyof typeof DiplomacyTier]

/** Thresholds offered in Settings for diplomacy-family mode (Blocked/None excluded). */
export const DIPLOMACY_COLOR_THRESHOLD_OPTIONS = [
  { value: DiplomacyTier.AMBASSADOR, label: 'Ambassador' },
  { value: DiplomacyTier.SAFE_PASSAGE, label: 'Safe Passage' },
  { value: DiplomacyTier.SHARE_INTEL, label: 'Share Intel' },
  { value: DiplomacyTier.FULL_ALLIANCE, label: 'Full Alliance' },
] as const

export type DiplomacyColorThreshold = (typeof DIPLOMACY_COLOR_THRESHOLD_OPTIONS)[number]['value']

export const DEFAULT_DIPLOMACY_COLOR_THRESHOLD: DiplomacyColorThreshold =
  DiplomacyTier.SAFE_PASSAGE

export function isDiplomacyColorThreshold(value: number): value is DiplomacyColorThreshold {
  return (
    value === DiplomacyTier.AMBASSADOR ||
    value === DiplomacyTier.SAFE_PASSAGE ||
    value === DiplomacyTier.SHARE_INTEL ||
    value === DiplomacyTier.FULL_ALLIANCE
  )
}
