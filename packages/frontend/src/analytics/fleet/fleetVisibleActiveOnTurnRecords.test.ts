import { describe, expect, it } from 'vitest'
import type { FleetPlayerStreamSlice } from './fleetTablePlayerStreamState'
import type { FleetTableRecord } from './fleetTableWireSchema'
import { visibleActiveOnTurnFleetRecords } from './fleetVisibleActiveOnTurnRecords'

function record(partial: Partial<FleetTableRecord> & Pick<FleetTableRecord, 'recordId'>): FleetTableRecord {
  return {
    disposition: 'active',
    qualifiers: {},
    fields: {
      shipId: { kind: 'known', value: 1 },
      hull: { kind: 'known', value: 13 },
      engine: { kind: 'unknown' },
      beams: { kind: 'unknown' },
      launchers: { kind: 'unknown' },
      builtTurn: { kind: 'unknown' },
      location: { kind: 'unknown' },
    },
    buildOptionSets: [],
    ...partial,
  }
}

function streamSlice(
  playerName: string,
  records: FleetTableRecord[]
): FleetPlayerStreamSlice {
  return {
    playerName,
    records,
    discrepancyOverlay: 'inherit',
    isComplete: true,
    isFinal: true,
    isPending: false,
    summary: 'ok',
    error: null,
  }
}

describe('visibleActiveOnTurnFleetRecords', () => {
  it('yields visible active records last seen on the display turn', () => {
    const byId = new Map<number, FleetPlayerStreamSlice>([
      [
        1,
        streamSlice('Alice', [
          record({
            recordId: 'a-on-turn',
            lastSeen: { turn: 9, x: 10, y: 20 },
          }),
          record({
            recordId: 'a-stale',
            lastSeen: { turn: 8, x: 11, y: 21 },
          }),
          record({
            recordId: 'a-lost',
            disposition: 'lost',
            lastSeen: { turn: 9, x: 12, y: 22 },
          }),
          record({ recordId: 'a-no-pos' }),
        ]),
      ],
      [
        2,
        streamSlice('Bob', [
          record({
            recordId: 'b-hidden',
            lastSeen: { turn: 9, x: 30, y: 40 },
          }),
        ]),
      ],
    ])

    const entries = [
      ...visibleActiveOnTurnFleetRecords(byId, [{ playerId: 1, name: 'Alice shell' }], 9),
    ]
    expect(entries).toHaveLength(1)
    expect(entries[0]).toMatchObject({
      playerId: 1,
      playerName: 'Alice',
      lastSeen: { turn: 9, x: 10, y: 20 },
    })
    expect(entries[0]!.record.recordId).toBe('a-on-turn')
  })

  it('yields nothing when the stream slice is missing', () => {
    const entries = [
      ...visibleActiveOnTurnFleetRecords(new Map(), [{ playerId: 3, name: 'Carol' }], 9),
    ]
    expect(entries).toEqual([])
  })
})
