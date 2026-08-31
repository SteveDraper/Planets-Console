import { describe, expect, it } from 'vitest'
import { readInferenceSolution } from './scoresWireParsers'

describe('readInferenceSolution', () => {
  it('parses shipBuilds with hullId for icon rendering', () => {
    const parsed = readInferenceSolution({
      objectiveValue: 80,
      actions: [],
      shipBuilds: [
        {
          comboId: 'combo_60_4_none_none_0_0',
          label: 'Build Ruby Class Light Cruiser: 2x SuperStarDrive 4',
          count: 1,
          hullId: 60,
          engineId: 4,
          beamId: null,
          torpId: null,
          beamCount: 0,
          launcherCount: 0,
        },
      ],
    })

    expect(parsed).toMatchObject({
      objectiveValue: 80,
      shipBuilds: [
        {
          comboId: 'combo_60_4_none_none_0_0',
          hullId: 60,
          engineId: 4,
          beamCount: 0,
          launcherCount: 0,
        },
      ],
    })
  })

  it('parses counterpartyPlayerId on gift/trade/acquired actions', () => {
    const parsed = readInferenceSolution({
      objectiveValue: 0,
      actions: [
        {
          actionId: 'gift:warship:to:3:point:40',
          label: 'Gift warship to player 3',
          count: 1,
          counterpartyPlayerId: 3,
        },
      ],
    })
    expect(parsed?.actions[0]).toEqual({
      actionId: 'gift:warship:to:3:point:40',
      label: 'Gift warship to player 3',
      count: 1,
      counterpartyPlayerId: 3,
    })
  })
})
