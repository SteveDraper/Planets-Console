import { describe, expect, it } from 'vitest'
import {
  inboundRelationFromByPlayerId,
  turnRelationsFromPayload,
} from './turnRelations'

describe('turnRelationsFromPayload', () => {
  it('parses relation rows from turn ensure payload', () => {
    const edges = turnRelationsFromPayload({
      relations: [
        {
          playerid: 10,
          playertoid: 2,
          relationfrom: 2,
          relationto: 1,
          color: '#fff',
        },
        { playerid: 10, playertoid: 3, relationfrom: 0, relationto: 0 },
        { playerid: 'bad', playertoid: 1, relationfrom: 1, relationto: 1 },
      ],
    })
    expect(edges).toEqual([
      { playerid: 10, playertoid: 2, relationfrom: 2, relationto: 1 },
      { playerid: 10, playertoid: 3, relationfrom: 0, relationto: 0 },
    ])
  })

  it('returns empty for missing relations', () => {
    expect(turnRelationsFromPayload(null)).toEqual([])
    expect(turnRelationsFromPayload({})).toEqual([])
  })
})

describe('inboundRelationFromByPlayerId', () => {
  it('maps other players to relationfrom for the viewpoint', () => {
    const map = inboundRelationFromByPlayerId(
      [
        { playerid: 10, playertoid: 2, relationfrom: 2, relationto: 1 },
        { playerid: 10, playertoid: 10, relationfrom: 4, relationto: 4 },
        { playerid: 2, playertoid: 10, relationfrom: 4, relationto: 2 },
      ],
      10
    )
    expect([...map.entries()]).toEqual([[2, 2]])
  })
})
