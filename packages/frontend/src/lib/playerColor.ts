/**
 * Shared player identity colors for map/table paint.
 * Build an immutable {@link PlayerColorPaintSnapshot}, then
 * {@link resolvePlayerColor}. Non-React callers use {@link colorForPlayerId}.
 */

import { tonalVariantForFamilyMember } from './colorTone'
import {
  DEFAULT_DIPLOMACY_COLOR_THRESHOLD,
  type DiplomacyColorThreshold,
} from './diplomacyTier'

export {
  diplomacyFamilyToneOrderIds,
  tonalVariantForFamilyMember,
} from './colorTone'

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
