import { describe, expect, it } from 'vitest'
import type { TableDataResponse } from '../api/bff'
import { turnRacePlayerLabelsFromTable } from './turnRacePlayerLabels'

describe('turnRacePlayerLabelsFromTable', () => {
  it('builds a player-id map from scoreboard rows', () => {
    const data: TableDataResponse = {
      analyticId: 'scores',
      columns: ['Race (player)', 'Military'],
      rowPlayerIds: [8, 9],
      rows: [
        ['The Solar Federation (dougp314)', '100'],
        ['The Evil Empire (alice)', '90'],
      ],
    }

    expect(turnRacePlayerLabelsFromTable(data)).toEqual(
      new Map([
        [8, 'The Solar Federation (dougp314)'],
        [9, 'The Evil Empire (alice)'],
      ])
    )
  })

  it('returns an empty map for non-scores payloads', () => {
    expect(
      turnRacePlayerLabelsFromTable({
        analyticId: 'fleet',
        columns: [],
        rows: [],
      })
    ).toEqual(new Map())
  })
})
