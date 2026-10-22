/**
 * Baked Territory movie palette, indexes 0 through 59.
 * Indexes 0 through 31 are the published prefix (index 0 `#8fff00`, index 31 `#fff48f`).
 * Indexes 32 through 59 continue that prefix. The page only indexes this list.
 */

export type Rgb = readonly [number, number, number]

export type Lab = readonly [number, number, number]

export const TERRITORY_MOVIE_PALETTE = [
  '#8fff00', '#00006e', '#ffc0ff', '#1f3c00', '#bd2d00', '#00dcff', '#ffae00', '#3974fd',
  '#d0008e', '#809276', '#290e00', '#fffcef', '#005a65', '#ff927e', '#826000', '#8e8593',
  '#00ffd2', '#4b475d', '#001313', '#7800f4', '#a7c1ff', '#a9ac00', '#c66aff', '#88032e',
  '#007f00', '#00959e', '#af8e69', '#00be57', '#fd0050', '#5f5e53', '#da7ca1', '#fff48f',
  '#865d57', '#40002f', '#0045a3', '#e76900', '#d4bcbd', '#663101', '#a8cdc3', '#03a2e6',
  '#845fa1', '#00785f', '#05001f', '#fed1a7', '#7f007f', '#d1ffc7', '#362e1a', '#c0bd92',
  '#787f23', '#04b99f', '#687c85', '#e7eaff', '#8f8bcd', '#00382d', '#9eaab3', '#76415d',
  '#b3827c', '#006b9b', '#a36538', '#ab8700',
] as const

const BAKED_LENGTH = TERRITORY_MOVIE_PALETTE.length

const XN = 0.9504559270516716
const YN = 1
const ZN = 1.0890577507598784
const LAB_EPSILON = 216 / 24389
const LAB_KAPPA = 24389 / 27

function linearizeSrgb(channel: number): number {
  const unit = channel / 255
  if (unit <= 0.04045) return unit / 12.92
  return ((unit + 0.055) / 1.055) ** 2.4
}

function labF(t: number): number {
  if (t > LAB_EPSILON) return Math.cbrt(t)
  return (LAB_KAPPA * t + 16) / 116
}

/** CIELAB from 8-bit sRGB, D65, no chromatic adaptation. */
export function srgbToLab(red: number, green: number, blue: number): Lab {
  const r = linearizeSrgb(red)
  const g = linearizeSrgb(green)
  const b = linearizeSrgb(blue)
  const x =
    0.41239079926595934 * r + 0.357584339383878 * g + 0.1804807884018343 * b
  const y =
    0.21263900587151027 * r + 0.715168678767756 * g + 0.07219231536073371 * b
  const z =
    0.01933081871559182 * r + 0.11919477979462598 * g + 0.9505321522496607 * b
  const fx = labF(x / XN)
  const fy = labF(y / YN)
  const fz = labF(z / ZN)
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)]
}

function cosDeg(degrees: number): number {
  return Math.cos((degrees * Math.PI) / 180)
}

function sinDeg(degrees: number): number {
  return Math.sin((degrees * Math.PI) / 180)
}

function hueDegrees(b: number, aPrime: number): number {
  const degrees = (Math.atan2(b, aPrime) * 180) / Math.PI
  return degrees < 0 ? degrees + 360 : degrees
}

/** CIEDE2000 with kL = kC = kH = 1. */
export function deltaE00(left: Lab, right: Lab): number {
  const [l1, a1, b1] = left
  const [l2, a2, b2] = right
  const c1 = Math.hypot(a1, b1)
  const c2 = Math.hypot(a2, b2)
  const cBar = (c1 + c2) / 2
  const cBar7 = cBar ** 7
  const g = 0.5 * (1 - Math.sqrt(cBar7 / (cBar7 + 25 ** 7)))
  const a1p = (1 + g) * a1
  const a2p = (1 + g) * a2
  const c1p = Math.hypot(a1p, b1)
  const c2p = Math.hypot(a2p, b2)
  const h1 = hueDegrees(b1, a1p)
  const h2 = hueDegrees(b2, a2p)
  let hueDelta = 0
  if (c1p * c2p !== 0) {
    hueDelta = h2 - h1
    if (hueDelta > 180) hueDelta -= 360
    else if (hueDelta < -180) hueDelta += 360
  }
  let hueMean = h1 + h2
  if (c1p * c2p !== 0) {
    if (Math.abs(h1 - h2) <= 180) hueMean = (h1 + h2) / 2
    else if (h1 + h2 < 360) hueMean = (h1 + h2 + 360) / 2
    else hueMean = (h1 + h2 - 360) / 2
  }
  const dL = l2 - l1
  const dC = c2p - c1p
  const dH = 2 * Math.sqrt(c1p * c2p) * sinDeg(hueDelta / 2)
  const t =
    1 -
    0.17 * cosDeg(hueMean - 30) +
    0.24 * cosDeg(2 * hueMean) +
    0.32 * cosDeg(3 * hueMean + 6) -
    0.2 * cosDeg(4 * hueMean - 63)
  const deltaTheta = 30 * Math.exp(-(((hueMean - 275) / 25) ** 2))
  const cBarPrime = (c1p + c2p) / 2
  const cBarPrime7 = cBarPrime ** 7
  const rc = 2 * Math.sqrt(cBarPrime7 / (cBarPrime7 + 25 ** 7))
  const lShift = (l1 + l2) / 2 - 50
  const sl = 1 + (0.015 * lShift * lShift) / Math.sqrt(20 + lShift * lShift)
  const sc = 1 + 0.045 * cBarPrime
  const sh = 1 + 0.015 * cBarPrime * t
  const rt = -sinDeg(2 * deltaTheta) * rc
  const termL = dL / sl
  const termC = dC / sc
  const termH = dH / sh
  return Math.sqrt(termL * termL + termC * termC + termH * termH + rt * termC * termH)
}

export function deltaE00Srgb(left: Rgb, right: Rgb): number {
  return deltaE00(srgbToLab(left[0], left[1], left[2]), srgbToLab(right[0], right[1], right[2]))
}

export function hexToRgb(hex: string): Rgb {
  const raw = hex.startsWith('#') ? hex.slice(1) : hex
  return [
    Number.parseInt(raw.slice(0, 2), 16),
    Number.parseInt(raw.slice(2, 4), 16),
    Number.parseInt(raw.slice(4, 6), 16),
  ]
}

export function rgbToHex(rgb: Rgb): string {
  const channels = rgb.map((channel) => channel.toString(16).padStart(2, '0'))
  return `#${channels.join('')}`
}

/**
 * First candidate whose minimum distance is strictly greatest.
 * An equal distance keeps the earlier candidate, so lexicographic RGB order
 * is the tie break when candidates are scanned in that order.
 */
export function chooseMaximin(candidates: readonly { rgb: Rgb; minDistance: number }[]): Rgb | null {
  let best: Rgb | null = null
  let bestDistance = -1
  for (const candidate of candidates) {
    if (candidate.minDistance > bestDistance) {
      bestDistance = candidate.minDistance
      best = candidate.rgb
    }
  }
  return best
}

/** Unused sRGB triple that maximizes the minimum CIEDE2000 distance to `existing`. */
export function pickMaximinRgb(existing: readonly Rgb[], candidates: readonly Rgb[]): Rgb | null {
  const existingLabs = existing.map((rgb) => srgbToLab(rgb[0], rgb[1], rgb[2]))
  const scored = candidates.map((rgb) => {
    const lab = srgbToLab(rgb[0], rgb[1], rgb[2])
    let minDistance = Infinity
    for (const painted of existingLabs) {
      const distance = deltaE00(lab, painted)
      if (distance < minDistance) minDistance = distance
    }
    if (existingLabs.length === 0) minDistance = Infinity
    return { rgb, minDistance }
  })
  return chooseMaximin(scored)
}

function packRgb(rgb: Rgb): number {
  return (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]
}

/**
 * Exhaustive lex scan of the 8-bit cube. Yields so a legend longer than 60
 * does not freeze the shell for the whole search. Indexes already chosen stay fixed.
 */
export async function nextMaximinSrgb(existing: readonly Rgb[]): Promise<Rgb> {
  const chosen = new Set(existing.map(packRgb))
  const existingLabs = existing.map((rgb) => srgbToLab(rgb[0], rgb[1], rgb[2]))
  let best: Rgb | null = null
  let bestDistance = -1
  let scanned = 0
  for (let red = 0; red < 256; red += 1) {
    for (let green = 0; green < 256; green += 1) {
      for (let blue = 0; blue < 256; blue += 1) {
        if (chosen.has((red << 16) | (green << 8) | blue)) continue
        const lab = srgbToLab(red, green, blue)
        let minDistance = Infinity
        for (const painted of existingLabs) {
          const distance = deltaE00(lab, painted)
          if (distance < minDistance) minDistance = distance
          if (minDistance <= bestDistance) break
        }
        if (minDistance > bestDistance) {
          bestDistance = minDistance
          best = [red, green, blue]
        }
        scanned += 1
        if ((scanned & 0x3ffff) === 0) await Promise.resolve()
      }
    }
  }
  if (best == null) {
    throw new Error('Territory movie palette has no further color.')
  }
  return best
}

/** At least the 60 baked colors. A longer legend appends maximin colors after index 59. */
export async function moviePalette(
  ownerCount: number,
  nextColor: (existing: readonly Rgb[]) => Promise<Rgb> = nextMaximinSrgb
): Promise<string[]> {
  const colors: string[] = [...TERRITORY_MOVIE_PALETTE]
  const target = Math.max(BAKED_LENGTH, ownerCount)
  while (colors.length < target) {
    const rgb = await nextColor(colors.map(hexToRgb))
    colors.push(rgbToHex(rgb))
  }
  return colors
}
