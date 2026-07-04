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
    expect(next.discrepancyOverlay).toBe('set')
    expect(next.discrepancy).toEqual(ledgerPlayer.discrepancy)
  })

  it('clears discrepancy overlay when ledger has none', () => {
    const event: FleetTableStreamEvent = {
      type: 'ledger_updated',
      playerId: 8,
      ledger: { ...ledgerPlayer, discrepancy: undefined },
    }

    const next = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), event)

    expect(next.discrepancyOverlay).toBe('clear')
    expect(next.discrepancy).toBeUndefined()
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

  it('updates provenance summary while materializing', () => {
    const next = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), {
      type: 'provenance',
      playerId: 8,
      turnEvidenceAtN: false,
      priorLedgerAtNMinus1: false,
      isFinal: false,
    })

    expect(next.summary).toBe('Collecting turn evidence')
    expect(next.isPending).toBe(false)
  })

  it('marks failure from error events', () => {
    const next = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), {
      type: 'error',
      playerId: 8,
      detail: 'stream ended early',
    })

    expect(next.isComplete).toBe(true)
    expect(next.error).toBe('stream ended early')
    expect(next.summary).toBe('stream ended early')
    expect(fleetPlayerStreamSliceFromState(next)?.error).toBe('stream ended early')
  })
})

describe('mergeFleetPlayerWithStreamSlice', () => {
  const restDiscrepancy = {
    hostTurn: 111,
    activeRowCount: 2,
    scoreboardImpliedCount: 1,
  }

  const basePlayer: FleetTablePlayer = {
    playerId: 8,
    playerName: 'Alice REST',
    records: [baseRecord],
    discrepancy: restDiscrepancy,
  }

  const streamSliceBase = {
    records: [refinedRecord],
    isComplete: true,
    isFinal: true,
    isPending: false,
    summary: 'ok',
    error: null,
  } as const

  it('prefers stream records over REST when present', () => {
    const merged = mergeFleetPlayerWithStreamSlice(basePlayer, {
      ...streamSliceBase,
      discrepancyOverlay: 'inherit',
    }, 'Alice shell')

    expect(merged.records).toEqual([refinedRecord])
    expect(merged.playerName).toBe('Alice REST')
  })

  it('falls back to REST when stream has no record overlay', () => {
    const merged = mergeFleetPlayerWithStreamSlice(basePlayer, undefined, 'Alice shell')

    expect(merged.records).toEqual([baseRecord])
    expect(merged.playerName).toBe('Alice REST')
  })

  it('inherits REST discrepancy when stream overlay is inherit', () => {
    const merged = mergeFleetPlayerWithStreamSlice(basePlayer, {
      ...streamSliceBase,
      discrepancyOverlay: 'inherit',
    }, 'Alice shell')

    expect(merged.discrepancy).toEqual(restDiscrepancy)
  })

  it('uses stream discrepancy when overlay is set', () => {
    const streamDiscrepancy = {
      hostTurn: 99,
      activeRowCount: 3,
      scoreboardImpliedCount: 2,
    }

    const merged = mergeFleetPlayerWithStreamSlice(basePlayer, {
      ...streamSliceBase,
      discrepancyOverlay: 'set',
      discrepancy: streamDiscrepancy,
    }, 'Alice shell')

    expect(merged.discrepancy).toEqual(streamDiscrepancy)
  })

  it('omits discrepancy when stream overlay is clear', () => {
    const merged = mergeFleetPlayerWithStreamSlice(basePlayer, {
      ...streamSliceBase,
      discrepancyOverlay: 'clear',
    }, 'Alice shell')

    expect(merged.discrepancy).toBeUndefined()
  })
})

describe('fleetPlayerStreamSliceFromState', () => {
  it('returns null for untouched initial state without pending flag', () => {
    const state = initialFleetPlayerStreamState()
    expect(fleetPlayerStreamSliceFromState({ ...state, isPending: false })).toBeNull()
  })

  it('publishes pending slice from initial state', () => {
    expect(fleetPlayerStreamSliceFromState(initialFleetPlayerStreamState())).toEqual({
      discrepancyOverlay: 'inherit',
      isComplete: false,
      isFinal: false,
      isPending: true,
      summary: 'Fleet materialization in progress',
      error: null,
    })
  })

  it('publishes set overlay and discrepancy from ledger state', () => {
    const state = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), {
      type: 'ledger_updated',
      playerId: 8,
      ledger: ledgerPlayer,
    })

    expect(fleetPlayerStreamSliceFromState(state)).toEqual({
      playerName: 'Alice',
      records: [refinedRecord],
      discrepancyOverlay: 'set',
      discrepancy: ledgerPlayer.discrepancy,
      isComplete: false,
      isFinal: false,
      isPending: false,
      summary: 'Refining fleet records',
      error: null,
    })
  })

  it('publishes clear overlay when ledger has no discrepancy', () => {
    const state = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), {
      type: 'ledger_updated',
      playerId: 8,
      ledger: { ...ledgerPlayer, discrepancy: undefined },
    })

    const slice = fleetPlayerStreamSliceFromState(state)

    expect(slice?.discrepancyOverlay).toBe('clear')
    expect(slice).not.toHaveProperty('discrepancy')
  })
})
