import { DiplomacyTier } from '../../lib/diplomacyTier'
import {
  colorFromOverrideOrDefault,
  playerColorOverrideStorageKey,
  type PlayerColorPaintSnapshot,
} from '../../lib/playerColor'
import {
  DEFAULT_MINEFIELD_STANCE_COLORS,
  minefieldTypeId,
  type MinefieldPaintPolicy,
  type MinefieldTypeId,
} from './types'

export type MinefieldTypePreferencesById = Record<MinefieldTypeId, MinefieldTypePreferences>

export type MinefieldTypePreferences = {
  enabled: boolean
  policy: MinefieldPaintPolicy
  stanceInColor: string
  stanceOutColor: string
}

export function defaultMinefieldTypePreferences(): MinefieldTypePreferencesById {
  return {
    normal: {
      enabled: true,
      policy: 'owner',
      stanceInColor: DEFAULT_MINEFIELD_STANCE_COLORS.normal.in,
      stanceOutColor: DEFAULT_MINEFIELD_STANCE_COLORS.normal.out,
    },
    web: {
      enabled: true,
      policy: 'stance',
      stanceInColor: DEFAULT_MINEFIELD_STANCE_COLORS.web.in,
      stanceOutColor: DEFAULT_MINEFIELD_STANCE_COLORS.web.out,
    },
  }
}

/** Always the per-player palette (overrides + preset), ignoring global player color mode. */
export function minefieldOwnerColor(
  ownerId: number,
  snapshot: PlayerColorPaintSnapshot
): string {
  return colorFromOverrideOrDefault(
    ownerId,
    snapshot.overrides[playerColorOverrideStorageKey(ownerId)]
  )
}

/**
 * Stance buckets: viewpoint's own fields plus inbound ``relationfrom >= Safe Passage``.
 * Locked to Safe Passage; ignores Settings diplomacy color threshold.
 */
export function isMinefieldStanceInCircle(
  ownerId: number,
  viewpointPlayerId: number | null,
  inboundRelationFromByPlayerId: ReadonlyMap<number, number>
): boolean {
  if (viewpointPlayerId != null && ownerId === viewpointPlayerId) {
    return true
  }
  const relationFrom = inboundRelationFromByPlayerId.get(ownerId)
  return relationFrom != null && relationFrom >= DiplomacyTier.SAFE_PASSAGE
}

export function resolveMinefieldPaintColor(args: {
  isWeb: boolean
  ownerId: number
  preferences: MinefieldTypePreferences
  paintSnapshot: PlayerColorPaintSnapshot
  viewpointPlayerId: number | null
  inboundRelationFromByPlayerId: ReadonlyMap<number, number>
}): string {
  if (args.preferences.policy === 'owner') {
    return minefieldOwnerColor(args.ownerId, args.paintSnapshot)
  }
  const inCircle = isMinefieldStanceInCircle(
    args.ownerId,
    args.viewpointPlayerId,
    args.inboundRelationFromByPlayerId
  )
  return inCircle ? args.preferences.stanceInColor : args.preferences.stanceOutColor
}

export function minefieldTypePreferences(
  types: MinefieldTypePreferencesById,
  isWeb: boolean
): MinefieldTypePreferences {
  return types[minefieldTypeId(isWeb)]
}
