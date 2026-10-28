import type { FleetTableStreamEvent } from '../../api/fleetTableStreamEventSchema'
import type { FleetCountDiscrepancy, FleetTablePlayer, FleetTableRecord } from './fleetTableWireSchema'

export const FLEET_MATERIALIZATION_PENDING_SUMMARY = 'Fleet materialization in progress'

export type FleetDiscrepancyOverlay = 'inherit' | 'set' | 'clear'

/** Turn-load roster: a stored ledger, or this turn's sightings when no file exists. */
export type FleetRosterPaint = 'sightings' | 'ledger'

/**
 * Map picture for one player. A stored ledger is the paint, including an
 * approximate fleet and a ledger subject to revision. Sightings are the paint
 * only while this turn has no ledger. A host-turn ledger save replaces it.
 * Stream updates that do not save a ledger leave this picture in place.
 */
export type FleetMapPaint = {
  source: FleetRosterPaint
  playerName: string
  records: readonly FleetTableRecord[]
}

export type FleetPlayerStreamSlice = {
  playerName?: string
  records?: readonly FleetTableRecord[]
  rosterPaint?: FleetRosterPaint
  mapPaint?: FleetMapPaint
  discrepancyOverlay: FleetDiscrepancyOverlay
  discrepancy?: FleetCountDiscrepancy
  isComplete: boolean
  isFinal: boolean
  isPending: boolean
  summary: string
  error: string | null
}

export type FleetPlayerStreamState = {
  playerName: string | null
  records: FleetTableRecord[] | null
  rosterPaint: FleetRosterPaint | null
  mapPaint: FleetMapPaint | null
  discrepancyOverlay: FleetDiscrepancyOverlay
  discrepancy?: FleetCountDiscrepancy
  isComplete: boolean
  isFinal: boolean
  isPending: boolean
  summary: string
  error: string | null
}

export function initialFleetPlayerStreamState(): FleetPlayerStreamState {
  return {
    playerName: null,
    records: null,
    rosterPaint: null,
    mapPaint: null,
    discrepancyOverlay: 'inherit',
    isComplete: false,
    isFinal: false,
    isPending: true,
    summary: FLEET_MATERIALIZATION_PENDING_SUMMARY,
    error: null,
  }
}

export function pendingFleetPlayerStreamSlice(): FleetPlayerStreamSlice {
  return {
    discrepancyOverlay: 'inherit',
    isComplete: false,
    isFinal: false,
    isPending: true,
    summary: FLEET_MATERIALIZATION_PENDING_SUMMARY,
    error: null,
  }
}

function upsertRecord(
  records: FleetTableRecord[],
  record: FleetTableRecord
): FleetTableRecord[] {
  const index = records.findIndex((entry) => entry.recordId === record.recordId)
  if (index < 0) {
    return [...records, record]
  }
  const next = [...records]
  next[index] = record
  return next
}

function ledgerDisplayState(
  ledger: FleetTablePlayer
): Pick<FleetPlayerStreamState, 'playerName' | 'records' | 'discrepancyOverlay' | 'discrepancy'> {
  const hasDiscrepancy = ledger.discrepancy != null
  return {
    playerName: ledger.playerName,
    records: [...ledger.records],
    discrepancyOverlay: hasDiscrepancy ? 'set' : 'clear',
    discrepancy: ledger.discrepancy,
  }
}

function mapPaintFromLedger(
  source: FleetRosterPaint,
  ledger: FleetTablePlayer
): FleetMapPaint {
  return {
    source,
    playerName: ledger.playerName,
    records: [...ledger.records],
  }
}

function provenanceSummary(event: Extract<FleetTableStreamEvent, { type: 'provenance' }>): string {
  if (!event.turnEvidenceAtN) {
    return 'Collecting turn evidence'
  }
  if (!event.priorLedgerAtNMinus1) {
    return 'Building prior ledger'
  }
  if (!event.isFinal) {
    return 'Refining fleet records'
  }
  return 'Finalizing fleet ledger'
}

export function reduceFleetPlayerStreamState(
  state: FleetPlayerStreamState,
  event: FleetTableStreamEvent
): FleetPlayerStreamState {
  if (event.type === 'roster_paint') {
    return {
      ...state,
      ...ledgerDisplayState(event.ledger),
      rosterPaint: event.paint,
      mapPaint: mapPaintFromLedger(event.paint, event.ledger),
      error: null,
    }
  }

  if (event.type === 'ledger_updated') {
    const progress = {
      isPending: !state.isComplete,
      summary: state.isComplete ? state.summary : 'Refining fleet records',
    }
    // Hold the painted roster. An unpainted stream still shows this ledger.
    // Map paint changes only when this event saves the host-turn ledger.
    if (state.rosterPaint != null && event.replacesTurnLoad === false) {
      return {
        ...state,
        ...progress,
      }
    }
    const savesHostTurnLedger = event.replacesTurnLoad !== false
    return {
      ...state,
      ...ledgerDisplayState(event.ledger),
      ...progress,
      rosterPaint: null,
      mapPaint: savesHostTurnLedger
        ? mapPaintFromLedger('ledger', event.ledger)
        : state.mapPaint,
      error: null,
    }
  }

  if (event.type === 'record_refined') {
    // A painted roster stays until a replacing ledger writes records.
    if (state.rosterPaint != null) {
      return state
    }
    const baseRecords = state.records ?? []
    return {
      ...state,
      records: upsertRecord(baseRecords, event.record),
      isPending: !state.isComplete,
      error: null,
    }
  }

  if (event.type === 'provenance') {
    return {
      ...state,
      isFinal: event.isFinal,
      isPending: !event.isFinal && !state.isComplete,
      summary: state.isComplete ? state.summary : provenanceSummary(event),
    }
  }

  if (event.type === 'complete') {
    return {
      ...state,
      isComplete: true,
      isFinal: event.isFinal,
      isPending: false,
      summary: event.summary,
      error: null,
    }
  }

  if (event.type === 'error') {
    return {
      ...state,
      isComplete: true,
      isPending: false,
      error: event.detail,
      summary: event.detail,
    }
  }

  return state
}

export function fleetPlayerStreamSliceFromState(
  state: FleetPlayerStreamState
): FleetPlayerStreamSlice | null {
  const hasProgressMetadata =
    state.summary !== FLEET_MATERIALIZATION_PENDING_SUMMARY || state.isFinal

  if (
    !state.isPending &&
    state.records == null &&
    state.playerName == null &&
    state.discrepancyOverlay === 'inherit' &&
    state.error == null &&
    !state.isComplete &&
    !hasProgressMetadata
  ) {
    return null
  }

  const slice: FleetPlayerStreamSlice = {
    discrepancyOverlay: state.discrepancyOverlay,
    isComplete: state.isComplete,
    isFinal: state.isFinal,
    isPending: state.isPending,
    summary: state.summary,
    error: state.error,
  }

  if (state.playerName != null) {
    slice.playerName = state.playerName
  }
  if (state.records != null) {
    slice.records = state.records
  }
  if (state.rosterPaint != null) {
    slice.rosterPaint = state.rosterPaint
  }
  if (state.mapPaint != null) {
    slice.mapPaint = state.mapPaint
  }
  if (state.discrepancyOverlay === 'set' && state.discrepancy != null) {
    slice.discrepancy = state.discrepancy
  }

  return slice
}

function resolveFleetDiscrepancy(
  streamSlice: FleetPlayerStreamSlice | undefined
): FleetCountDiscrepancy | undefined {
  switch (streamSlice?.discrepancyOverlay) {
    case 'set':
      return streamSlice.discrepancy
    case 'clear':
      return undefined
    default:
      return undefined
  }
}

export function fleetPlayerFromStreamSlice(
  streamSlice: FleetPlayerStreamSlice | undefined,
  fallbackPlayerName: string
): {
  playerName: string
  records: readonly FleetTableRecord[]
  discrepancy?: FleetCountDiscrepancy
  streamError: string | null
  streamSlice: FleetPlayerStreamSlice | undefined
} {
  const playerName = streamSlice?.playerName ?? fallbackPlayerName
  const records = streamSlice?.records ?? []
  const discrepancy = resolveFleetDiscrepancy(streamSlice)

  return {
    playerName,
    records,
    ...(discrepancy != null ? { discrepancy } : {}),
    streamError: streamSlice?.error ?? null,
    streamSlice,
  }
}
