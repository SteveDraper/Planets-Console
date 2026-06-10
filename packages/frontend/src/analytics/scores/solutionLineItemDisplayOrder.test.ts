import { describe, expect, it } from 'vitest'
import type { MilitaryScoreLineItem } from './inferenceConstraints'
import { sortSolutionLineItemsForDisplay } from './solutionLineItemDisplayOrder'

function line(actionId: string, label = actionId): MilitaryScoreLineItem {
  return {
    actionId,
    label,
    count: 1,
    scoreDelta2xPerUnit: 1,
    militaryChangePerUnit: 1,
    scoreDelta2xSubtotal: 1,
    militaryChangeSubtotal: 1,
  }
}

describe('sortSolutionLineItemsForDisplay', () => {
  it('orders ships, starbase defense, planet defense, fighters, then torps', () => {
    const sorted = sortSolutionLineItemsForDisplay([
      line('ship_torps_loaded_6', 'Mark 8 torps'),
      line('ship_fighters_added_total', 'Ship fighters'),
      line('planet_defense_posts_added_total', 'Planet defense'),
      line('combo_13_9_3_6_8_6', 'Missouri'),
      line('starbase_defense_posts_added_total', 'Starbase defense'),
      line('fighters_starbase_to_ship', 'Fighters to ship'),
      line('combo_freighter', 'Freighter'),
    ])

    expect(sorted.map((item) => item.actionId)).toEqual([
      'combo_13_9_3_6_8_6',
      'combo_freighter',
      'starbase_defense_posts_added_total',
      'planet_defense_posts_added_total',
      'ship_fighters_added_total',
      'fighters_starbase_to_ship',
      'ship_torps_loaded_6',
    ])
  })

  it('preserves original order within the same category', () => {
    const sorted = sortSolutionLineItemsForDisplay([
      line('combo_freighter', 'Freighter'),
      line('combo_13_9_3_6_8_6', 'Missouri'),
    ])

    expect(sorted.map((item) => item.label)).toEqual(['Freighter', 'Missouri'])
  })
})
