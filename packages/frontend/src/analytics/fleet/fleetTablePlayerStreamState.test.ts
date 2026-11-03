import { describe, expect, it } from 'vitest'
import type { FleetTableStreamEvent } from '../../api/fleetTableStreamEventSchema'
import {
  fleetPlayerFromStreamSlice,
  fleetPlayerStreamSliceFromState,
  initialFleetPlayerStreamState,
  reduceFleetPlayerStreamState,
} from './fleetTablePlayerStreamState'
import { isFleetTileMaterializing } from './fleetTileStatus'
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
  it('keeps sighting rows until a ledger save replaces them', () => {
    const sighting = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), {
      type: 'roster_paint',
      playerId: 8,
      paint: 'sightings',
      ledger: {
        playerId: 8,
        playerName: 'Alice',
        records: [baseRecord],
      },
    })
    expect(sighting.records).toEqual([baseRecord])
    expect(sighting.playerName).toBe('Alice')
    expect(sighting.rosterPaint).toBe('sightings')
    expect(sighting.mapPaint).toEqual({
      source: 'sightings',
      playerName: 'Alice',
      records: [baseRecord],
    })
    expect(sighting.discrepancyOverlay).toBe('clear')
    expect(fleetPlayerStreamSliceFromState(sighting)?.freshness).toBe('turn-load')

    const accepted = reduceFleetPlayerStreamState(sighting, { type: 'work_accepted' })
    expect(fleetPlayerStreamSliceFromState(accepted)?.freshness).toBe('none')
    expect(accepted.records).toEqual([baseRecord])

    const refined = reduceFleetPlayerStreamState(sighting, {
      type: 'record_refined',
      playerId: 8,
      record: refinedRecord,
    })
    expect(refined).toBe(sighting)

    const interim = reduceFleetPlayerStreamState(refined, {
      type: 'ledger_updated',
      playerId: 8,
      replacesTurnLoad: false,
      ledger: { ...ledgerPlayer, playerName: 'Interim' },
    })
    expect(interim.records).toEqual([baseRecord])
    expect(interim.playerName).toBe('Alice')
    expect(interim.discrepancy).toBeUndefined()
    expect(interim.discrepancyOverlay).toBe('clear')
    expect(interim.rosterPaint).toBe('sightings')
    expect(interim.mapPaint).toEqual(sighting.mapPaint)
    expect(interim.summary).toBe('Refining fleet records')

    const interimSlice = fleetPlayerStreamSliceFromState(interim)
    expect(interimSlice?.freshness).toBe('turn-load')
    expect(interimSlice?.rosterPaint).toBe('sightings')
    expect(fleetPlayerFromStreamSlice(interimSlice ?? undefined, 'fallback').records).toEqual([
      baseRecord,
    ])

    const saved = reduceFleetPlayerStreamState(interim, {
      type: 'ledger_updated',
      playerId: 8,
      ledger: ledgerPlayer,
    })
    expect(saved.records).toEqual([refinedRecord])
    expect(saved.rosterPaint).toBeNull()
    expect(saved.mapPaint).toEqual({
      source: 'ledger',
      playerName: 'Alice',
      records: [refinedRecord],
    })
    expect(saved.playerName).toBe('Alice')
    expect(saved.discrepancyOverlay).toBe('set')
    expect(saved.discrepancy).toEqual(ledgerPlayer.discrepancy)
    expect(fleetPlayerStreamSliceFromState(saved)?.freshness).toBe('none')
    const savedSlice = fleetPlayerStreamSliceFromState(saved)
    expect(savedSlice?.rosterPaint).toBeUndefined()
    expect(fleetPlayerFromStreamSlice(savedSlice ?? undefined, 'fallback').records).toEqual([
      refinedRecord,
    ])
    expect(fleetPlayerFromStreamSlice(savedSlice ?? undefined, 'fallback').discrepancy).toEqual(
      ledgerPlayer.discrepancy
    )
  })

  it('replaces a painted roster when replacesTurnLoad is true', () => {
    const painted = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), {
      type: 'roster_paint',
      playerId: 8,
      paint: 'sightings',
      ledger: {
        playerId: 8,
        playerName: 'Alice',
        records: [baseRecord],
      },
    })
    const saved = reduceFleetPlayerStreamState(painted, {
      type: 'ledger_updated',
      playerId: 8,
      replacesTurnLoad: true,
      ledger: ledgerPlayer,
    })

    expect(saved.records).toEqual([refinedRecord])
    expect(saved.rosterPaint).toBeNull()
    expect(saved.mapPaint?.source).toBe('ledger')
    expect(saved.mapPaint?.records).toEqual([refinedRecord])
    expect(saved.discrepancy).toEqual(ledgerPlayer.discrepancy)
  })

  it('keeps map paint when the table refines after a ledger save', () => {
    const saved = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), {
      type: 'ledger_updated',
      playerId: 8,
      ledger: ledgerPlayer,
    })
    const refinedAgain: FleetTableRecord = {
      ...refinedRecord,
      fields: {
        ...refinedRecord.fields,
        builtTurn: { kind: 'known', value: 99 },
      },
    }
    const refined = reduceFleetPlayerStreamState(saved, {
      type: 'record_refined',
      playerId: 8,
      record: refinedAgain,
    })
    const priorTurn = reduceFleetPlayerStreamState(refined, {
      type: 'ledger_updated',
      playerId: 8,
      replacesTurnLoad: false,
      ledger: { ...ledgerPlayer, playerName: 'Prior', records: [baseRecord] },
    })

    expect(refined.records).toEqual([refinedAgain])
    expect(refined.mapPaint).toEqual(saved.mapPaint)
    expect(priorTurn.records).toEqual([baseRecord])
    expect(priorTurn.playerName).toBe('Prior')
    expect(priorTurn.mapPaint).toEqual(saved.mapPaint)
  })

  it('writes an unpainted ledger that does not replace the turn load', () => {
    const next = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), {
      type: 'ledger_updated',
      playerId: 8,
      replacesTurnLoad: false,
      ledger: { ...ledgerPlayer, records: [baseRecord] },
    })

    expect(next.records).toEqual([baseRecord])
    expect(next.playerName).toBe('Alice')
    expect(next.discrepancyOverlay).toBe('set')
    expect(next.discrepancy).toEqual(ledgerPlayer.discrepancy)
    expect(next.rosterPaint).toBeNull()
    expect(next.mapPaint).toBeNull()
    expect(next.summary).toBe('Refining fleet records')

    const refined = reduceFleetPlayerStreamState(next, {
      type: 'record_refined',
      playerId: 8,
      record: refinedRecord,
    })
    expect(refined.records).toEqual([refinedRecord])
    expect(refined.rosterPaint).toBeNull()
  })

  it('shows a stored ledger, including one that is still open', () => {
    const painted = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), {
      type: 'roster_paint',
      playerId: 8,
      paint: 'ledger',
      ledger: ledgerPlayer,
    })
    const slice = fleetPlayerStreamSliceFromState(painted)
    const merged = fleetPlayerFromStreamSlice(slice ?? undefined, 'fallback')

    expect(painted.records).toEqual([refinedRecord])
    expect(painted.playerName).toBe('Alice')
    expect(painted.rosterPaint).toBe('ledger')
    expect(painted.mapPaint).toEqual({
      source: 'ledger',
      playerName: 'Alice',
      records: [refinedRecord],
    })
    expect(painted.discrepancyOverlay).toBe('set')
    expect(painted.discrepancy).toEqual(ledgerPlayer.discrepancy)
    expect(slice?.rosterPaint).toBe('ledger')
    expect(slice?.freshness).toBe('none')
    expect(slice?.records).toEqual([refinedRecord])
    expect(merged.records).toEqual([refinedRecord])
    expect(merged.discrepancy).toEqual(ledgerPlayer.discrepancy)
    expect(merged.playerName).toBe('Alice')
  })

  it('paints a stored ledger behind the mark as provisional and keeps that beside busy chrome', () => {
    const painted = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), {
      type: 'roster_paint',
      playerId: 8,
      paint: 'ledger',
      evidenceGeneration: 1,
      evidenceMark: 4,
      ledger: ledgerPlayer,
    })
    expect(fleetPlayerStreamSliceFromState(painted)?.freshness).toBe('subject-to-revision')

    const writing = reduceFleetPlayerStreamState(painted, {
      type: 'ledger_write',
      playerId: 8,
      writing: true,
    })
    expect(writing.ledgerWriting).toBe(true)
    expect(writing.freshness.hasStoredRow).toBe(true)
    const writingSlice = fleetPlayerStreamSliceFromState(writing)
    expect(writingSlice?.freshness).toBe('subject-to-revision')
    expect(isFleetTileMaterializing(writingSlice ?? undefined)).toBe(true)
  })

  it('clears the ledger-write spinner when the write ends', () => {
    const writing = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), {
      type: 'ledger_write',
      playerId: 8,
      writing: true,
    })
    expect(writing.ledgerWriting).toBe(true)
    expect(isFleetTileMaterializing(fleetPlayerStreamSliceFromState(writing) ?? undefined)).toBe(
      true
    )

    const ended = reduceFleetPlayerStreamState(writing, {
      type: 'ledger_write',
      playerId: 8,
      writing: false,
    })

    expect(ended.ledgerWriting).toBe(false)
    expect(isFleetTileMaterializing(fleetPlayerStreamSliceFromState(ended) ?? undefined)).toBe(
      false
    )

    const painted = reduceFleetPlayerStreamState(ended, {
      type: 'roster_paint',
      playerId: 8,
      paint: 'ledger',
      ledger: ledgerPlayer,
    })
    const accepted = reduceFleetPlayerStreamState(painted, { type: 'work_accepted' })
    expect(painted.ledgerWriting).toBe(false)
    expect(accepted.ledgerWriting).toBe(false)
  })

  it('does not keep an abandoned ledger write across the next admission', () => {
    const writing = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), {
      type: 'ledger_write',
      playerId: 8,
      writing: true,
    })
    const painted = reduceFleetPlayerStreamState(writing, {
      type: 'roster_paint',
      playerId: 8,
      paint: 'ledger',
      evidenceGeneration: 1,
      evidenceMark: 4,
      ledger: ledgerPlayer,
    })
    const accepted = reduceFleetPlayerStreamState(writing, { type: 'work_accepted' })

    expect(painted.ledgerWriting).toBe(false)
    expect(fleetPlayerStreamSliceFromState(painted)?.freshness).toBe('subject-to-revision')
    expect(isFleetTileMaterializing(fleetPlayerStreamSliceFromState(painted) ?? undefined)).toBe(
      false
    )
    expect(accepted.ledgerWriting).toBe(false)
    expect(isFleetTileMaterializing(fleetPlayerStreamSliceFromState(accepted) ?? undefined)).toBe(
      false
    )
  })

  it('a host-turn ledger save is never turn load', () => {
    const onMark = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), {
      type: 'ledger_updated',
      playerId: 8,
      evidenceGeneration: 2,
      evidenceMark: 2,
      ledger: ledgerPlayer,
    })
    expect(fleetPlayerStreamSliceFromState(onMark)?.freshness).toBe('none')

    const behind = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), {
      type: 'ledger_updated',
      playerId: 8,
      evidenceGeneration: 1,
      evidenceMark: 3,
      ledger: ledgerPlayer,
    })
    expect(fleetPlayerStreamSliceFromState(behind)?.freshness).toBe('subject-to-revision')
  })

  it('records the evidence mark on sightings without treating them as a stored row', () => {
    const sighting = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), {
      type: 'roster_paint',
      playerId: 8,
      paint: 'sightings',
      evidenceMark: 4,
      ledger: {
        playerId: 8,
        playerName: 'Alice',
        records: [baseRecord],
      },
    })
    expect(sighting.freshness).toEqual({
      phase: 'turn-load',
      hasStoredRow: false,
      evidenceGeneration: null,
      evidenceMark: 4,
    })
    expect(fleetPlayerStreamSliceFromState(sighting)?.freshness).toBe('turn-load')
  })

  it('does not return a provisional ledger to turn load when sightings arrive', () => {
    const stored = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), {
      type: 'roster_paint',
      playerId: 8,
      paint: 'ledger',
      evidenceGeneration: 1,
      evidenceMark: 4,
      ledger: ledgerPlayer,
    })
    const sightings = reduceFleetPlayerStreamState(stored, {
      type: 'roster_paint',
      playerId: 8,
      paint: 'sightings',
      ledger: {
        playerId: 8,
        playerName: 'Alice',
        records: [baseRecord],
      },
    })
    expect(fleetPlayerStreamSliceFromState(sightings)?.freshness).toBe('subject-to-revision')
  })

  it('does not restore turn load when sightings arrive after accept', () => {
    const sighting = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), {
      type: 'roster_paint',
      playerId: 8,
      paint: 'sightings',
      ledger: {
        playerId: 8,
        playerName: 'Alice',
        records: [baseRecord],
      },
    })
    const accepted = reduceFleetPlayerStreamState(sighting, { type: 'work_accepted' })
    const again = reduceFleetPlayerStreamState(accepted, {
      type: 'roster_paint',
      playerId: 8,
      paint: 'sightings',
      ledger: {
        playerId: 8,
        playerName: 'Alice',
        records: [baseRecord],
      },
    })
    expect(fleetPlayerStreamSliceFromState(again)?.freshness).toBe('none')
  })

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

describe('fleetPlayerFromStreamSlice', () => {
  const streamSliceBase = {
    records: [refinedRecord],
    isComplete: true,
    isFinal: true,
    ledgerWriting: false,
    freshness: 'none',
    summary: 'ok',
    error: null,
  } as const

  it('uses stream records and player name when present', () => {
    const merged = fleetPlayerFromStreamSlice(
      {
        ...streamSliceBase,
        playerName: 'Alice stream',
        discrepancyOverlay: 'inherit',
      },
      'Alice shell'
    )

    expect(merged.records).toEqual([refinedRecord])
    expect(merged.playerName).toBe('Alice stream')
  })

  it('falls back to shell player name and empty records without a stream slice', () => {
    const merged = fleetPlayerFromStreamSlice(undefined, 'Alice shell')

    expect(merged.records).toEqual([])
    expect(merged.playerName).toBe('Alice shell')
  })

  it('omits discrepancy when stream overlay is inherit', () => {
    const merged = fleetPlayerFromStreamSlice(
      {
        ...streamSliceBase,
        discrepancyOverlay: 'inherit',
      },
      'Alice shell'
    )

    expect(merged.discrepancy).toBeUndefined()
  })

  it('uses stream discrepancy when overlay is set', () => {
    const streamDiscrepancy = {
      hostTurn: 99,
      activeRowCount: 3,
      scoreboardImpliedCount: 2,
    }

    const merged = fleetPlayerFromStreamSlice(
      {
        ...streamSliceBase,
        discrepancyOverlay: 'set',
        discrepancy: streamDiscrepancy,
      },
      'Alice shell'
    )

    expect(merged.discrepancy).toEqual(streamDiscrepancy)
  })

  it('omits discrepancy when stream overlay is clear', () => {
    const merged = fleetPlayerFromStreamSlice(
      {
        ...streamSliceBase,
        discrepancyOverlay: 'clear',
      },
      'Alice shell'
    )

    expect(merged.discrepancy).toBeUndefined()
  })
})

describe('fleetPlayerStreamSliceFromState', () => {
  it('publishes no freshness word before an admission event', () => {
    expect(fleetPlayerStreamSliceFromState(initialFleetPlayerStreamState())).toEqual({
      discrepancyOverlay: 'inherit',
      isComplete: false,
      isFinal: false,
      ledgerWriting: false,
      freshness: 'none',
      summary: '',
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
      mapPaint: {
        source: 'ledger',
        playerName: 'Alice',
        records: [refinedRecord],
      },
      discrepancyOverlay: 'set',
      discrepancy: ledgerPlayer.discrepancy,
      isComplete: false,
      isFinal: false,
      ledgerWriting: false,
      freshness: 'none',
      summary: 'Refining fleet records',
      error: null,
    })
  })

  it('publishes provenance-only slice before records arrive', () => {
    const state = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), {
      type: 'provenance',
      playerId: 8,
      turnEvidenceAtN: false,
      priorLedgerAtNMinus1: false,
      isFinal: false,
    })

    expect(fleetPlayerStreamSliceFromState(state)).toEqual({
      discrepancyOverlay: 'inherit',
      isComplete: false,
      isFinal: false,
      ledgerWriting: false,
      freshness: 'none',
      summary: 'Collecting turn evidence',
      error: null,
    })
  })

  it('keeps records visible while pending between gap legs', () => {
    const withRecords = reduceFleetPlayerStreamState(initialFleetPlayerStreamState(), {
      type: 'ledger_updated',
      playerId: 8,
      ledger: ledgerPlayer,
    })
    const betweenLegs = reduceFleetPlayerStreamState(withRecords, {
      type: 'provenance',
      playerId: 8,
      turnEvidenceAtN: true,
      priorLedgerAtNMinus1: true,
      isFinal: false,
    })

    const slice = fleetPlayerStreamSliceFromState(betweenLegs)

    expect(slice?.records).toEqual([refinedRecord])
    expect(slice?.summary).toBe('Refining fleet records')
  })
})
