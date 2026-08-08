/**
 * Shared player identity colors for map/table paint.
 * Shell + Settings install a resolution port; call sites use colorForPlayerId.
 */

import { hexToRgb } from './cartography/cartographyColor'
import {
  DEFAULT_DIPLOMACY_COLOR_THRESHOLD,
  type DiplomacyColorThreshold,
} from './diplomacyTier'

export const PLAYER_COLOR_PRESET = [
  '#38bdf8',
  '#f472b6',
  '#a78bfa',
  '#34d399',
  '#fbbf24',
  '#fb7185',
  '#22d3ee',
  '#a3e635',
  '#f97316',
  '#818cf8',
  '#2dd4bf',
  '#e879f9',
  '#60a5fa',
  '#f43f5e',
  '#c084fc',
  '#84cc16',
] as const

export type PlayerColorMode = 'per_player' | 'diplomacy_family'

export const DEFAULT_FAMILY_BASE_COLOR = '#34d399'

export type PlayerColorOverrides = Readonly<Record<string, string>>

const EMPTY_INBOUND = new Map<number, number>()

/** Paint inputs consulted by {@link colorForPlayerId}. */
export type PlayerColorResolutionPort = {
  getMode: () => PlayerColorMode
  getOverride: (playerId: number) => string | undefined
  getDiplomacyThreshold: () => DiplomacyColorThreshold
  getFamilyBaseColor: () => string
  getViewpointPlayerId: () => number | null
  getInboundRelationFromByPlayerId: () => ReadonlyMap<number, number>
}

const emptyResolutionPort: PlayerColorResolutionPort = {
  getMode: () => 'per_player',
  getOverride: () => undefined,
  getDiplomacyThreshold: () => DEFAULT_DIPLOMACY_COLOR_THRESHOLD,
  getFamilyBaseColor: () => DEFAULT_FAMILY_BASE_COLOR,
  getViewpointPlayerId: () => null,
  getInboundRelationFromByPlayerId: () => EMPTY_INBOUND,
}

let activeResolutionPort: PlayerColorResolutionPort = emptyResolutionPort

/** Install the resolution port consulted by {@link colorForPlayerId}. */
export function setPlayerColorResolutionPort(port: PlayerColorResolutionPort): void {
  activeResolutionPort = port
}

/** Restore the empty resolution port (tests / teardown). */
export function resetPlayerColorResolutionPort(): void {
  activeResolutionPort = emptyResolutionPort
}

/** Override-only install helper for tests that do not need full resolution inputs. */
export function setPlayerColorOverrideStore(store: {
  getOverride: (playerId: number) => string | undefined
}): void {
  setPlayerColorResolutionPort({
    ...emptyResolutionPort,
    getOverride: store.getOverride,
  })
}

/** Alias for {@link resetPlayerColorResolutionPort}. */
export function resetPlayerColorOverrideStore(): void {
  resetPlayerColorResolutionPort()
}

export function playerColorOverrideStorageKey(playerId: number): string {
  return String(playerId)
}

export function defaultColorForPlayerId(playerId: number): string {
  const length = PLAYER_COLOR_PRESET.length
  const index = ((playerId % length) + length) % length
  return PLAYER_COLOR_PRESET[index]!
}

/** Non-empty override wins; otherwise the preset default. */
export function colorFromOverrideOrDefault(
  playerId: number,
  override: string | undefined
): string {
  if (override != null && override.length > 0) {
    return override
  }
  return defaultColorForPlayerId(playerId)
}

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

function normalizeHexColor(hex: string): string | null {
  const trimmed = hex.trim()
  const raw = trimmed.startsWith('#') ? trimmed.slice(1) : trimmed
  if (!/^[0-9a-fA-F]{6}$/.test(raw)) {
    return null
  }
  return `#${raw.toLowerCase()}`
}

/**
 * Deterministic tonal variant of ``familyBaseColor`` for one family member.
 * Stable for a given (base, memberPlayerId, familyMemberIds set).
 */
export function tonalVariantForFamilyMember(
  familyBaseColor: string,
  memberPlayerId: number,
  familyMemberIds: readonly number[]
): string {
  const normalizedBase = normalizeHexColor(familyBaseColor) ?? DEFAULT_FAMILY_BASE_COLOR
  const sorted = [...familyMemberIds].sort((a, b) => a - b)
  const index = sorted.indexOf(memberPlayerId)
  if (index < 0) {
    return normalizedBase
  }
  const n = sorted.length
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

/** Players at or above threshold for the active viewpoint (excludes viewpoint). */
export function diplomacyColorFamilyMemberIds(
  inboundRelationFromByPlayerId: ReadonlyMap<number, number>,
  viewpointPlayerId: number | null,
  threshold: number
): number[] {
  if (viewpointPlayerId == null) {
    return []
  }
  const members: number[] = []
  for (const [otherId, relationFrom] of inboundRelationFromByPlayerId) {
    if (otherId === viewpointPlayerId) {
      continue
    }
    if (relationFrom >= threshold) {
      members.push(otherId)
    }
  }
  members.sort((a, b) => a - b)
  return members
}

function colorFromDiplomacyFamily(
  playerId: number,
  port: PlayerColorResolutionPort
): string | null {
  const viewpointPlayerId = port.getViewpointPlayerId()
  if (viewpointPlayerId == null || playerId === viewpointPlayerId) {
    return null
  }
  const threshold = port.getDiplomacyThreshold()
  const inbound = port.getInboundRelationFromByPlayerId()
  const relationFrom = inbound.get(playerId)
  if (relationFrom == null || relationFrom < threshold) {
    return null
  }
  const members = diplomacyColorFamilyMemberIds(inbound, viewpointPlayerId, threshold)
  return tonalVariantForFamilyMember(port.getFamilyBaseColor(), playerId, members)
}

/**
 * Resolve a player's paint color from the resolution port.
 * Non-React callers use this entry point. React paint that must update when
 * Settings or shell paint context change should use ``usePlayerColor``.
 */
export function colorForPlayerId(playerId: number): string {
  const port = activeResolutionPort
  if (port.getMode() === 'diplomacy_family') {
    const familyColor = colorFromDiplomacyFamily(playerId, port)
    if (familyColor != null) {
      return familyColor
    }
    return defaultColorForPlayerId(playerId)
  }
  return colorFromOverrideOrDefault(playerId, port.getOverride(playerId))
}
