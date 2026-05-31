/**
 * Black hole ergosphere sampling aligned with Planets.nu ``getBlackHoleBand``.
 * Duplicated in api/concepts/stellar_cartography/black_holes.py; keep in sync via
 * test-fixtures/black-hole-ergosphere-contract.json.
 */

import {
  ERGOSPHERE_BAND_COUNT,
  blackHoleErgosphereOuterLy,
  blackHoleHaloRadiusLy,
} from './stellarCartographyTheme'

export { ERGOSPHERE_BAND_COUNT, blackHoleErgosphereOuterLy, blackHoleHaloRadiusLy }

/** Band index at ``distLy`` from center, or ``null`` outside the ergosphere. Band ``0`` is lethal core. */
export function blackHoleBandAt(
  coreRadiusLy: number,
  bandWidthLy: number,
  distLy: number
): number | null {
  if (bandWidthLy <= 0) {
    return null
  }
  const outer = blackHoleErgosphereOuterLy(coreRadiusLy, bandWidthLy)
  if (distLy > outer) {
    return null
  }
  if (distLy <= coreRadiusLy) {
    return 0
  }
  return Math.min(
    ERGOSPHERE_BAND_COUNT,
    Math.max(1, Math.ceil((distLy - coreRadiusLy) / bandWidthLy))
  )
}

/** Max safe ordered warp at ``distLy``; ``null`` in core or outside ergosphere. */
export function blackHoleMaxWarpAt(
  coreRadiusLy: number,
  bandWidthLy: number,
  distLy: number
): number | null {
  const band = blackHoleBandAt(coreRadiusLy, bandWidthLy, distLy)
  if (band === null || band === 0) {
    return null
  }
  return band
}

/** Host predictor fuel bonus percent at ``distLy``; ``null`` in core or outside. */
export function blackHoleFuelSavingPercentAt(
  coreRadiusLy: number,
  bandWidthLy: number,
  distLy: number
): number | null {
  const band = blackHoleBandAt(coreRadiusLy, bandWidthLy, distLy)
  if (band === null || band === 0) {
    return null
  }
  return 10 - band
}

/** Inner and outer ergosphere band edges in ly (band 1 = innermost). */
export function blackHoleBandRadiiLy(
  coreRadiusLy: number,
  bandWidthLy: number,
  band: number
): { innerLy: number; outerLy: number } {
  return {
    innerLy: coreRadiusLy + (band - 1) * bandWidthLy,
    outerLy: coreRadiusLy + band * bandWidthLy,
  }
}
