import type { AnalyticShellScope } from '../../api/bff'
import { fetchScoresTableInferenceStream } from '../../api/bff'
import type { InferenceStreamEvent } from '../../api/inferenceStreamEventSchema'
import {
  connectAnalyticTableStream,
  connectAnalyticTableStreamUntilComplete,
  type AnalyticTableStreamConnectResult,
} from '../../lib/analyticTableStreamConnect'
import {
  bumpScoresInferenceRevision,
  clearBumpMemoryForScope,
  noteSolutionEvidenceChangeAndShouldBumpRevision,
} from '../../stores/scoresInferenceRevision'
import { parseFleetTorpInputStatus } from './fleetTorpInputStatus'

export function shouldBumpScoresInferenceRevision(
  event: InferenceStreamEvent,
  scope: AnalyticShellScope
): boolean {
  if (event.type === 'complete') {
    return true
  }
  if (event.type === 'solution') {
    return noteSolutionEvidenceChangeAndShouldBumpRevision(
      scope,
      event.playerId,
      event.solutions,
      parseFleetTorpInputStatus(event.fleetTorpInputStatus)
    )
  }
  return false
}

function interceptScoresInferenceEvent(
  event: InferenceStreamEvent,
  scope: AnalyticShellScope
): void {
  if (shouldBumpScoresInferenceRevision(event, scope)) {
    bumpScoresInferenceRevision(scope)
  }
}

export type TableInferenceStreamConnectResult = AnalyticTableStreamConnectResult

export async function connectTableInferenceStream(
  scope: AnalyticShellScope,
  playerIds: number[],
  handlers: {
    signal: AbortSignal
    onEvent: (event: InferenceStreamEvent) => void
  }
): Promise<TableInferenceStreamConnectResult> {
  return connectAnalyticTableStream(scope, playerIds, {
    fetchStream: fetchScoresTableInferenceStream,
    signal: handlers.signal,
    onEvent: handlers.onEvent,
    interceptEvent: interceptScoresInferenceEvent,
  })
}

export async function connectTableInferenceStreamUntilComplete(
  scope: AnalyticShellScope,
  playerIds: number[],
  handlers: {
    signal: AbortSignal
    onEvent: (event: InferenceStreamEvent) => void
    hasPendingRows: () => boolean
  }
): Promise<TableInferenceStreamConnectResult> {
  return connectAnalyticTableStreamUntilComplete(scope, playerIds, {
    fetchStream: fetchScoresTableInferenceStream,
    signal: handlers.signal,
    onEvent: handlers.onEvent,
    hasPending: handlers.hasPendingRows,
    interceptEvent: interceptScoresInferenceEvent,
    onBeforeIncompleteRetries: clearBumpMemoryForScope,
  })
}
