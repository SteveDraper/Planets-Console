import type { FleetTableStreamEvent } from '../../api/fleetTableStreamEventSchema'
import type {
  FleetCountDiscrepancy,
  FleetTablePlayer,
  FleetTableRecord,
} from './fleetTableWireSchema'

export type FleetDiscrepancyOverlay = 'inherit' | 'set' | 'clear'

export type FleetPlayerStreamSlice = {
  playerName?: string
  records?: readonly FleetTableRecord[]
  discrepancyOverlay: FleetDiscrepancyOverlay
  discrepancy?: FleetCountDiscrepancy
  isComplete: boolean
  isFinal: boolean
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
    summary: '',
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
      error: null,
    }
  }

  if (event.type === 'record_refined') {
    const baseRecords = state.records ?? []
    return {
      ...state,
      records: upsertRecord(baseRecords, event.record),
      error: null,
    }
  }

  if (event.type === 'provenance') {
    return {
      ...state,
      isFinal: event.isFinal,
    }
  }

  if (event.type === 'complete') {
    return {
      ...state,
      isComplete: true,
      isFinal: event.isFinal,
      summary: event.summary,
      error: null,
    }
  }

  if (event.type === 'error') {
    return {
      ...state,
      isComplete: true,
      error: event.detail,
      summary: event.detail,
    }
  }

  return state
}

export function fleetPlayerStreamSliceFromState(
  state: FleetPlayerStreamState
): FleetPlayerStreamSlice | null {
  if (
    state.records == null &&
    state.playerName == null &&
    state.discrepancyOverlay === 'inherit' &&
    state.error == null &&
    !state.isComplete
  ) {
    return null
  }

  const slice: FleetPlayerStreamSlice = {
    discrepancyOverlay: state.discrepancyOverlay,
    isComplete: state.isComplete,
    isFinal: state.isFinal,
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
  streamSlice: FleetPlayerStreamSlice | undefined,
  baseDiscrepancy: FleetCountDiscrepancy | undefined
): FleetCountDiscrepancy | undefined {
  switch (streamSlice?.discrepancyOverlay) {
    case 'set':
      return streamSlice.discrepancy
    case 'clear':
      return undefined
    default:
      return baseDiscrepancy
  }
}

export function mergeFleetPlayerWithStreamSlice(
  basePlayer: FleetTablePlayer | undefined,
  streamSlice: FleetPlayerStreamSlice | undefined,
  fallbackPlayerName: string
): {
  playerName: string
  records: readonly FleetTableRecord[]
  discrepancy?: FleetCountDiscrepancy
  streamError: string | null
} {
  const playerName = streamSlice?.playerName ?? basePlayer?.playerName ?? fallbackPlayerName
  const records = streamSlice?.records ?? basePlayer?.records ?? []
  const discrepancy = resolveFleetDiscrepancy(streamSlice, basePlayer?.discrepancy)

  return {
    playerName,
    records,
    ...(discrepancy != null ? { discrepancy } : {}),
    streamError: streamSlice?.error ?? null,
  }
}
