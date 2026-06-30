import type { AnalyticShellScope } from '../../api/bff'
import { fetchFleetTableStream } from '../../api/bff'
import type { FleetTableStreamEvent } from '../../api/fleetTableStreamEventSchema'
import {
  connectAnalyticTableStream,
  connectAnalyticTableStreamUntilComplete,
  type AnalyticTableStreamConnectResult,
} from '../../lib/analyticTableStreamConnect'

export const FLEET_TABLE_STREAM_ALREADY_ACTIVE_DETAIL =
  'A fleet table stream is already active for this scope.'

export type FleetTableStreamConnectResult = AnalyticTableStreamConnectResult

export async function connectFleetTableStream(
  scope: AnalyticShellScope,
  playerIds: number[],
  handlers: {
    signal: AbortSignal
    onEvent: (event: FleetTableStreamEvent) => void
  }
): Promise<FleetTableStreamConnectResult> {
  return connectAnalyticTableStream(scope, playerIds, {
    conflictAlreadyActiveDetail: FLEET_TABLE_STREAM_ALREADY_ACTIVE_DETAIL,
    fetchStream: fetchFleetTableStream,
    signal: handlers.signal,
    onEvent: handlers.onEvent,
  })
}

export async function connectFleetTableStreamUntilComplete(
  scope: AnalyticShellScope,
  playerIds: number[],
  handlers: {
    signal: AbortSignal
    onEvent: (event: FleetTableStreamEvent) => void
    hasPendingPlayers: () => boolean
  }
): Promise<FleetTableStreamConnectResult> {
  return connectAnalyticTableStreamUntilComplete(scope, playerIds, {
    conflictAlreadyActiveDetail: FLEET_TABLE_STREAM_ALREADY_ACTIVE_DETAIL,
    fetchStream: fetchFleetTableStream,
    signal: handlers.signal,
    onEvent: handlers.onEvent,
    hasPending: handlers.hasPendingPlayers,
  })
}
