import {
  HelpCircle,
  Rocket,
  Shield,
  Swords,
} from 'lucide-react'
import { describe, expect, it } from 'vitest'
import {
  classifyInferenceActionFamily,
  inferenceActionAggregateIcon,
  inferenceActionDisplayRank,
  isComboActionId,
  isDefenseRelatedActionId,
  isFighterActionId,
  isPlanetDefenseTotalActionId,
  isStarbaseDefenseTotalActionId,
  isTorpsLoadedActionId,
} from './inferenceActionFamily'

describe('inference action id predicates', () => {
  it('detects combo, fighter, torps, and defense patterns', () => {
    expect(isComboActionId('combo_freighter')).toBe(true)
    expect(isComboActionId('combo_13_9_3_6_8_6')).toBe(true)
    expect(isComboActionId('ship_torps_loaded_6')).toBe(false)

    expect(isStarbaseDefenseTotalActionId('starbase_defense_posts_added_total')).toBe(
      true
    )
    expect(isPlanetDefenseTotalActionId('planet_defense_posts_added_total')).toBe(
      true
    )

    expect(isFighterActionId('ship_fighters_added_total')).toBe(true)
    expect(isFighterActionId('fighters_starbase_to_ship')).toBe(true)
    expect(isFighterActionId('ship_torps_loaded_6')).toBe(false)

    expect(isTorpsLoadedActionId('ship_torps_loaded_6')).toBe(true)
    expect(isTorpsLoadedActionId('ship_fighters_added_total')).toBe(false)

    expect(isDefenseRelatedActionId('starbase_defense_posts_added_total')).toBe(
      true
    )
    expect(isDefenseRelatedActionId('custom_defense_upgrade')).toBe(true)
    expect(isDefenseRelatedActionId('ship_torps_loaded_6')).toBe(false)
  })
})

describe('classifyInferenceActionFamily', () => {
  it('maps representative action ids to sort families', () => {
    expect(classifyInferenceActionFamily('combo_freighter')).toBe('combo')
    expect(classifyInferenceActionFamily('starbase_defense_posts_added_total')).toBe(
      'starbase_defense_total'
    )
    expect(classifyInferenceActionFamily('planet_defense_posts_added_total')).toBe(
      'planet_defense_total'
    )
    expect(classifyInferenceActionFamily('fighters_starbase_to_ship')).toBe('fighter')
    expect(classifyInferenceActionFamily('ship_torps_loaded_6')).toBe('torps_loaded')
    expect(classifyInferenceActionFamily('unknown_action')).toBe('other')
  })
})

describe('inferenceActionDisplayRank', () => {
  it('assigns the player-facing sort order', () => {
    expect(inferenceActionDisplayRank('combo_freighter')).toBe(0)
    expect(inferenceActionDisplayRank('starbase_defense_posts_added_total')).toBe(1)
    expect(inferenceActionDisplayRank('planet_defense_posts_added_total')).toBe(2)
    expect(inferenceActionDisplayRank('ship_fighters_added_total')).toBe(3)
    expect(inferenceActionDisplayRank('ship_torps_loaded_6')).toBe(4)
    expect(inferenceActionDisplayRank('unknown_action')).toBe(5)
  })

  it('ranks other defense-related ids after torps', () => {
    expect(inferenceActionDisplayRank('custom_defense_upgrade')).toBe(5)
  })
})

describe('inferenceActionAggregateIcon', () => {
  it('maps aggregate rows to Lucide icons with torps and fighter precedence', () => {
    expect(inferenceActionAggregateIcon('ship_torps_loaded_6')).toBe(Rocket)
    expect(inferenceActionAggregateIcon('ship_fighters_added_total')).toBe(Swords)
    expect(inferenceActionAggregateIcon('fighters_starbase_to_ship')).toBe(Swords)
    expect(inferenceActionAggregateIcon('starbase_defense_posts_added_total')).toBe(
      Shield
    )
    expect(inferenceActionAggregateIcon('planet_defense_posts_added_total')).toBe(
      Shield
    )
    expect(inferenceActionAggregateIcon('custom_defense_upgrade')).toBe(Shield)
    expect(inferenceActionAggregateIcon('unknown_action')).toBe(HelpCircle)
  })
})
