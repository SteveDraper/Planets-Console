/** Planets.nu Large Deep Space Freighter -- generic freighter glyph stand-in. */
export const GENERIC_FREIGHTER_HULL_ID = 17

const MOBILE_PLANETS_NU_BASE = 'https://mobile.planets.nu'

/** Hull ids with 3D portrait assets on the Planets.nu mobile CDN (from nu.js HULLS3D). */
const HULLS_3D = new Set([
  1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25,
  26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48,
  49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71,
  72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94,
  95, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114,
  115, 117, 118, 119, 120, 121, 122, 123, 150, 151, 152, 153, 154, 155, 156, 157, 158, 159, 160,
  161, 162, 163, 164, 165, 166, 167, 168, 169, 170, 201, 202, 203, 204, 205, 206, 207, 208, 209,
  210, 211,
])

export type HullImageUrlOptions = {
  /** Classic 2D hull art instead of 3D portrait (nu.js account classicpics). */
  classic?: boolean
  /** Left-facing classic art (nu.js left flag). */
  left?: boolean
  /** Side-view 3D art instead of portrait (nu.js sideview). */
  sideview?: boolean
  /** Beam count suffix for hulls 65 and 71 in classic mode. */
  beams?: number
  /** CDN base override (defaults to mobile.planets.nu). */
  baseUrl?: string
}

/** Normalize race-variant hull ids (1000/2000/3000 offsets) to master catalog id. */
export function normalizeHullPictureId(hullId: number): number {
  if (hullId > 3000) {
    return hullId - 3000
  }
  if (hullId > 2000) {
    return hullId - 2000
  }
  if (hullId > 1000) {
    return hullId - 1000
  }
  return hullId
}

function classicPictureId(baseId: number, beams: number | undefined): number | string {
  if (beams != null && beams > 0 && (baseId === 65 || baseId === 71)) {
    return `${baseId}-${beams}`
  }
  return baseId
}

/**
 * Planets.nu mobile client hull image URL (nu.js hullImg parity).
 * Default: 3D portrait `{baseId}_p.png` when the hull has a 3D asset.
 */
export function hullImageUrl(hullId: number, options: HullImageUrlOptions = {}): string {
  const baseUrl = options.baseUrl ?? MOBILE_PLANETS_NU_BASE
  const baseId = normalizeHullPictureId(hullId)
  const useClassic = options.classic === true || !HULLS_3D.has(baseId)
  const picId = classicPictureId(baseId, options.beams)

  if (!useClassic) {
    if (!options.sideview) {
      return `${baseUrl}/img/hulls3d/${baseId}_p.png`
    }
    if (options.left) {
      return `${baseUrl}/img/hullsleft3d/${baseId}.png`
    }
    return `${baseUrl}/img/hulls3d/${baseId}.png`
  }

  if (options.left) {
    return `${baseUrl}/img/hullsleft/${picId}.png`
  }
  return `${baseUrl}/img/hulls/${picId}.png`
}
