/**
 * Hex / HSL tonal helpers for deterministic family color variants.
 * Reuses {@link hexToRgb} from cartographyColor.
 */

import { hexToRgb } from './cartography/cartographyColor'

function clamp01(value: number): number {
  if (value < 0) return 0
  if (value > 1) return 1
  return value
}

function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  const rn = r / 255
  const gn = g / 255
  const bn = b / 255
  const max = Math.max(rn, gn, bn)
  const min = Math.min(rn, gn, bn)
  const l = (max + min) / 2
  if (max === min) {
    return [0, 0, l]
  }
  const d = max - min
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
  let h = 0
  switch (max) {
    case rn:
      h = ((gn - bn) / d + (gn < bn ? 6 : 0)) / 6
      break
    case gn:
      h = ((bn - rn) / d + 2) / 6
      break
    default:
      h = ((rn - gn) / d + 4) / 6
      break
  }
  return [h, s, l]
}

function hueToRgb(p: number, q: number, t: number): number {
  let tt = t
  if (tt < 0) tt += 1
  if (tt > 1) tt -= 1
  if (tt < 1 / 6) return p + (q - p) * 6 * tt
  if (tt < 1 / 2) return q
  if (tt < 2 / 3) return p + (q - p) * (2 / 3 - tt) * 6
  return p
}

function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  if (s === 0) {
    const v = Math.round(l * 255)
    return [v, v, v]
  }
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s
  const p = 2 * l - q
  return [
    Math.round(hueToRgb(p, q, h + 1 / 3) * 255),
    Math.round(hueToRgb(p, q, h) * 255),
    Math.round(hueToRgb(p, q, h - 1 / 3) * 255),
  ]
}

function componentToHex(value: number): string {
  const clamped = Math.max(0, Math.min(255, value))
  return clamped.toString(16).padStart(2, '0')
}

function rgbToHex(r: number, g: number, b: number): string {
  return `#${componentToHex(r)}${componentToHex(g)}${componentToHex(b)}`
}

/** Normalize to lowercase `#rrggbb`, or null if not a 6-digit hex color. */
export function normalizeHexColor(hex: string): string | null {
  const trimmed = hex.trim()
  const raw = trimmed.startsWith('#') ? trimmed.slice(1) : trimmed
  if (!/^[0-9a-fA-F]{6}$/.test(raw)) {
    return null
  }
  return `#${raw.toLowerCase()}`
}

/**
 * Tone assignment order: other members by ascending id, then ``brightestMemberId``
 * last so they receive the highest lightness.
 */
export function diplomacyFamilyToneOrderIds(
  familyMemberIds: readonly number[],
  brightestMemberId: number | null | undefined
): number[] {
  const sorted = [...familyMemberIds].sort((a, b) => a - b)
  if (brightestMemberId == null || !sorted.includes(brightestMemberId)) {
    return sorted
  }
  return [...sorted.filter((id) => id !== brightestMemberId), brightestMemberId]
}

/**
 * Deterministic tonal variant of ``familyBaseColor`` for one family member.
 * Stable for a given (base, memberPlayerId, familyMemberIds set, brightestMemberId).
 * ``brightestMemberId`` always gets the brightest tone when present.
 */
export function tonalVariantForFamilyMember(
  familyBaseColor: string,
  memberPlayerId: number,
  familyMemberIds: readonly number[],
  brightestMemberId?: number | null
): string {
  const normalizedBase = normalizeHexColor(familyBaseColor) ?? '#34d399'
  const ordered = diplomacyFamilyToneOrderIds(familyMemberIds, brightestMemberId)
  const index = ordered.indexOf(memberPlayerId)
  if (index < 0) {
    return normalizedBase
  }
  const n = ordered.length
  const [r, g, b] = hexToRgb(normalizedBase)
  const [h, s, baseL] = rgbToHsl(r, g, b)
  if (n <= 1) {
    return normalizedBase
  }
  const span = Math.min(0.28, 0.08 * (n - 1))
  const t = index / (n - 1)
  const lightness = clamp01(baseL - span / 2 + t * span)
  const saturation = clamp01(s * (0.92 + 0.16 * (1 - Math.abs(t - 0.5) * 2)))
  const [nr, ng, nb] = hslToRgb(h, saturation, lightness)
  return rgbToHex(nr, ng, nb)
}
