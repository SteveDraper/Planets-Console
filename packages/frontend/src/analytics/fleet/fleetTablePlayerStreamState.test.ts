import { describe, expect, it } from 'vitest'
import type { FleetTableStreamEvent } from '../../api/fleetTableStreamEventSchema'
import {
  fleetPlayerStreamSliceFromState,
  initialFleetPlayerStreamState,
  mergeFleetPlayerWithStreamSlice,
  reduceFleetPlayerStreamState,
} from './fleetTablePlayerStreamState'
import type { FleetTablePlayer, FleetTableRecord } from './fleetTableWireSchema'

const baseRecord: FleetTableRecord = {
  recordId: 'rec-1',
  disposition: 'active',
  qualifiers: {},
  fields: {
    shipId: { kind: 'known', value: 1 },
    hull: { kind: 'unknown' },
    engine: { kind: 'unknown' },
    beams: { kind: 'unknown' },
    launchers: { kind: 'unknown' },
    builtTurn: { kind: 'unknown' },
    location: { kind: 'unknown' },
  },
  buildOptionSets: [],
}

const refinedRecord: FleetTableRecord = {
  ...baseRecord,
  fields: {
    ...baseRecord.fields,
    hull: { kind: 'known', value: 13 },
    builtTurn: { kind: 'known', value: 4 },
  },
  buildOptionSets: [
    {
      comboId: 'combo_a',
      label: 'Option A',
      solutionRankWeight: 10,
      hullId: 13,
      engineId: 9,
      beamId: 3,
      beamCount: 8,
      launcherCount: 6,
      torpId: 6,
    },
  ],
}

const ledgerPlayer: FleetTablePlayer = {
  playerId: 8,
  playerName: 'Alice',
  records: [refinedRecord],
  discrepancy: {
    hostTurn: 111,
    activeRowCount: 1,
    scoreboardImpliedCount: 1,
  },
}

describe('reduceFleetPlayerStreamState', () => {
  it('replaces records from ledger_updated', () => {
    const event: FleetTableStreamEvent = {
      type: 'ledger_updated',
      playerId: 8,
      ledger: ledgerPlayer,
    }

    const next = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), event)

    expect(next.records).toEqual([refinedRecord])
    expect(next.playerName).toBe('Alice')
    expect(next.discrepancy).toEqual(ledgerPlayer.discrepancy)
  })

  it('upserts a single record from record_refined', () => {
    const withBase = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), {
      type: 'ledger_updated',
      playerId: 8,
      ledger: { ...ledgerPlayer, records: [baseRecord] },
    })

    const next = reduceFleetPlayerStreamState(withBase, {
      type: 'record_refined',
      playerId: 8,
      record: refinedRecord,
    })

    expect(next.records).toEqual([refinedRecord])
  })

  it('marks completion from complete events', () => {
    const next = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), {
      type: 'complete',
      playerId: 8,
      isFinal: true,
      summary: 'done',
    })

    expect(next.isComplete).toBe(true)
    expect(next.isFinal).toBe(true)
    expect(next.summary).toBe('done')
  })
})

describe('mergeFleetPlayerWithStreamSlice', () => {
  const basePlayer: FleetTablePlayer = {
    playerId: 8,
    playerName: 'Alice REST',
    records: [baseRecord],
  }

  it('prefers stream records over REST when present', () => {
    const merged = mergeFleetPlayerWithStreamSlice(basePlayer, {
      records: [refinedRecord],
      isComplete: true,
      isFinal: true,
      summary: 'ok',
      error: null,
    }, 'Alice shell')

    expect(merged.records).toEqual([refinedRecord])
    expect(merged.playerName).toBe('Alice REST')
  })

  it('falls back to REST when stream has no record overlay', () => {
    const merged = mergeFleetPlayerWithStreamSlice(basePlayer, undefined, 'Alice shell')

    expect(merged.records).toEqual([baseRecord])
    expect(merged.playerName).toBe('Alice REST')
  })
})

describe('fleetPlayerStreamSliceFromState', () => {
  it('returns null for untouched initial state', () => {
    expect(fleetPlayerStreamSliceFromState(initialFleetPlayerStreamState())).toBeNull()
  })
})
