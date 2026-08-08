/**
 * Shared player identity colors for map/table paint.
 * Build an immutable {@link PlayerColorPaintSnapshot}, then
 * {@link resolvePlayerColor}. Non-React callers use {@link colorForPlayerId}.
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

/** Default base for the diplomacy circle (in-threshold) family. */
export const DEFAULT_FAMILY_BASE_COLOR = '#34d399'

/** Default base for the out-of-circle family -- chosen for contrast with the in-circle default. */
export const DEFAULT_OUT_OF_CIRCLE_BASE_COLOR = '#f43f5e'

export type PlayerColorOverrides = Readonly<Record<string, string>>

const EMPTY_INBOUND = new Map<number, number>()
const EMPTY_ROSTER: readonly number[] = []

/** Inputs used to build an immutable paint snapshot. */
export type PlayerColorPaintSnapshotInputs = {
  mode: PlayerColorMode
  overrides: PlayerColorOverrides
  diplomacyThreshold: DiplomacyColorThreshold
  familyBaseColor: string
  outOfCircleBaseColor: string
  viewpointPlayerId: number | null
  inboundRelationFromByPlayerId: ReadonlyMap<number, number>
  rosterPlayerIds: readonly number[]
}

/**
 * Immutable paint policy inputs. Family membership is precomputed at build time
 * so resolve is a pure lookup + tonal variant.
 */
export type PlayerColorPaintSnapshot = Readonly<{
  mode: PlayerColorMode
  overrides: PlayerColorOverrides
  familyBaseColor: string
  outOfCircleBaseColor: string
  viewpointPlayerId: number | null
  inCircleMemberIds: readonly number[]
  outOfCircleMemberIds: readonly number[]
}>

/** Thin port: non-React {@link colorForPlayerId} reads the active snapshot. */
export type PlayerColorResolutionPort = {
  getSnapshot: () => PlayerColorPaintSnapshot
}

export const EMPTY_PLAYER_COLOR_PAINT_SNAPSHOT: PlayerColorPaintSnapshot = {
  mode: 'per_player',
  overrides: {},
  familyBaseColor: DEFAULT_FAMILY_BASE_COLOR,
  outOfCircleBaseColor: DEFAULT_OUT_OF_CIRCLE_BASE_COLOR,
  viewpointPlayerId: null,
  inCircleMemberIds: EMPTY_ROSTER,
  outOfCircleMemberIds: EMPTY_ROSTER,
}

const emptyResolutionPort: PlayerColorResolutionPort = {
  getSnapshot: () => EMPTY_PLAYER_COLOR_PAINT_SNAPSHOT,
}

let activeResolutionPort: PlayerColorResolutionPort = emptyResolutionPort

/** Install the snapshot port consulted by {@link colorForPlayerId}. */
export function setPlayerColorResolutionPort(port: PlayerColorResolutionPort): void {
  activeResolutionPort = port
}

/** Restore the empty snapshot port (tests / teardown). */
export function resetPlayerColorResolutionPort(): void {
  activeResolutionPort = emptyResolutionPort
}

/**
 * Build an immutable paint snapshot, precomputing in-circle and out-of-circle
 * membership for diplomacy-family resolve.
 */
export function buildPlayerColorPaintSnapshot(
  inputs: PlayerColorPaintSnapshotInputs
): PlayerColorPaintSnapshot {
  const inCircleMemberIds = diplomacyColorFamilyMemberIds(
    inputs.inboundRelationFromByPlayerId,
    inputs.viewpointPlayerId,
    inputs.diplomacyThreshold
  )
  const outOfCircleMemberIds = outOfCircleFamilyMemberIds(
    inputs.rosterPlayerIds,
    inCircleMemberIds
  )
  return {
    mode: inputs.mode,
    overrides: inputs.overrides,
    familyBaseColor: inputs.familyBaseColor,
    outOfCircleBaseColor: inputs.outOfCircleBaseColor,
    viewpointPlayerId: inputs.viewpointPlayerId,
    inCircleMemberIds,
    outOfCircleMemberIds,
  }
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
 * ``brightestMemberId`` (viewpoint) always gets the brightest tone when present.
 */
export function tonalVariantForFamilyMember(
  familyBaseColor: string,
  memberPlayerId: number,
  familyMemberIds: readonly number[],
  brightestMemberId?: number | null
): string {
  const normalizedBase = normalizeHexColor(familyBaseColor) ?? DEFAULT_FAMILY_BASE_COLOR
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

/**
 * Diplomacy circle (in-family): viewpoint (always) plus others with inbound grant
 * ``relationfrom >= threshold``.
 */
export function diplomacyColorFamilyMemberIds(
  inboundRelationFromByPlayerId: ReadonlyMap<number, number>,
  viewpointPlayerId: number | null,
  threshold: number
): number[] {
  if (viewpointPlayerId == null) {
    return []
  }
  const members: number[] = [viewpointPlayerId]
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

/** Roster players not in the diplomacy circle. */
export function outOfCircleFamilyMemberIds(
  rosterPlayerIds: readonly number[],
  diplomacyCircleMemberIds: readonly number[]
): number[] {
  const inCircle = new Set(diplomacyCircleMemberIds)
  const members = rosterPlayerIds.filter((id) => !inCircle.has(id))
  members.sort((a, b) => a - b)
  return members
}

function colorFromDiplomacyFamily(
  playerId: number,
  snapshot: PlayerColorPaintSnapshot
): string | null {
  if (snapshot.viewpointPlayerId == null) {
    return null
  }
  if (snapshot.inCircleMemberIds.includes(playerId)) {
    return tonalVariantForFamilyMember(
      snapshot.familyBaseColor,
      playerId,
      snapshot.inCircleMemberIds,
      snapshot.viewpointPlayerId
    )
  }
  let outCircle = snapshot.outOfCircleMemberIds
  if (!outCircle.includes(playerId)) {
    // Painted id missing from roster still gets out-of-circle paint as a singleton.
    outCircle = [...outCircle, playerId].sort((a, b) => a - b)
  }
  return tonalVariantForFamilyMember(
    snapshot.outOfCircleBaseColor,
    playerId,
    outCircle,
    null
  )
}

/** Pure paint policy: resolve a player color from an immutable snapshot. */
export function resolvePlayerColor(
  playerId: number,
  snapshot: PlayerColorPaintSnapshot
): string {
  if (snapshot.mode === 'diplomacy_family') {
    const familyColor = colorFromDiplomacyFamily(playerId, snapshot)
    if (familyColor != null) {
      return familyColor
    }
    return defaultColorForPlayerId(playerId)
  }
  return colorFromOverrideOrDefault(
    playerId,
    snapshot.overrides[playerColorOverrideStorageKey(playerId)]
  )
}

/**
 * Resolve a player's paint color from the active snapshot port.
 * Non-React callers use this entry point. React paint that must update when
 * Settings or shell paint context change should use ``usePlayerColor``.
 */
export function colorForPlayerId(playerId: number): string {
  return resolvePlayerColor(playerId, activeResolutionPort.getSnapshot())
}

/** Default snapshot inputs (empty shell context, default knobs). */
export function defaultPlayerColorPaintSnapshotInputs(): PlayerColorPaintSnapshotInputs {
  return {
    mode: 'per_player',
    overrides: {},
    diplomacyThreshold: DEFAULT_DIPLOMACY_COLOR_THRESHOLD,
    familyBaseColor: DEFAULT_FAMILY_BASE_COLOR,
    outOfCircleBaseColor: DEFAULT_OUT_OF_CIRCLE_BASE_COLOR,
    viewpointPlayerId: null,
    inboundRelationFromByPlayerId: EMPTY_INBOUND,
    rosterPlayerIds: EMPTY_ROSTER,
  }
}
