import {
  HelpCircle,
  Rocket,
  Shield,
  Swords,
  type LucideIcon,
} from 'lucide-react'

/** Sort/display families for inference solution line action ids. */
export type InferenceActionFamily =
  | 'combo'
  | 'starbase_defense_total'
  | 'planet_defense_total'
  | 'fighter'
  | 'torps_loaded'
  | 'other'

export function isComboActionId(actionId: string): boolean {
  return actionId.startsWith('combo_')
}

export function isStarbaseDefenseTotalActionId(actionId: string): boolean {
  return actionId === 'starbase_defense_posts_added_total'
}

export function isPlanetDefenseTotalActionId(actionId: string): boolean {
  return actionId === 'planet_defense_posts_added_total'
}

export function isFighterActionId(actionId: string): boolean {
  return actionId.includes('fighter') || actionId.startsWith('fighters_')
}

export function isTorpsLoadedActionId(actionId: string): boolean {
  return actionId.startsWith('ship_torps_loaded_')
}

/** Broader than sort defense totals; used for aggregate Shield icons. */
export function isDefenseRelatedActionId(actionId: string): boolean {
  return actionId.includes('defense')
}

const DISPLAY_RANK_BY_FAMILY: Record<InferenceActionFamily, number> = {
  combo: 0,
  starbase_defense_total: 1,
  planet_defense_total: 2,
  fighter: 3,
  torps_loaded: 4,
  other: 5,
}

export function classifyInferenceActionFamily(
  actionId: string
): InferenceActionFamily {
  if (isComboActionId(actionId)) {
    return 'combo'
  }
  if (isStarbaseDefenseTotalActionId(actionId)) {
    return 'starbase_defense_total'
  }
  if (isPlanetDefenseTotalActionId(actionId)) {
    return 'planet_defense_total'
  }
  if (isFighterActionId(actionId)) {
    return 'fighter'
  }
  if (isTorpsLoadedActionId(actionId)) {
    return 'torps_loaded'
  }
  return 'other'
}

export function inferenceActionDisplayRank(actionId: string): number {
  return DISPLAY_RANK_BY_FAMILY[classifyInferenceActionFamily(actionId)]
}

export function inferenceActionAggregateIcon(actionId: string): LucideIcon {
  if (isTorpsLoadedActionId(actionId)) {
    return Rocket
  }
  if (isFighterActionId(actionId)) {
    return Swords
  }
  if (isDefenseRelatedActionId(actionId)) {
    return Shield
  }
  return HelpCircle
}
