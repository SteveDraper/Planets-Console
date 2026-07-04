import type { FleetTableStreamEvent } from '../../api/fleetTableStreamEventSchema'
import type { FleetCountDiscrepancy, FleetTableRecord } from './fleetTableWireSchema'

export const FLEET_MATERIALIZATION_PENDING_SUMMARY = 'Fleet materialization in progress'

export type FleetDiscrepancyOverlay = 'inherit' | 'set' | 'clear'

export type FleetPlayerStreamSlice = {
  playerName?: string
  records?: readonly FleetTableRecord[]
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
  if (event.type === 'ledger_updated') {
    const ledger = event.ledger
    const hasDiscrepancy = ledger.discrepancy != null
    return {
      ...state,
      playerName: ledger.playerName,
      records: [...ledger.records],
      discrepancyOverlay: hasDiscrepancy ? 'set' : 'clear',
      discrepancy: ledger.discrepancy,
      isPending: !state.isComplete,
      summary: state.isComplete ? state.summary : 'Refining fleet records',
      error: null,
    }
  }

  if (event.type === 'record_refined') {
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
