import type * as bff from '../../api/bff'
import type { AnalyticShellScope, TableDataResponse } from '../../api/bff'
import type { InferenceStreamEvent } from '../../api/inferenceStreamEventSchema'

export type StreamHandlers = Parameters<typeof bff.fetchScoresTableInferenceStream>[2]

export const scope: AnalyticShellScope = {
  gameId: '628580',
  turn: 111,
  perspective: 1,
}

export const tableData: TableDataResponse = {
  analyticId: 'scores',
  includeBuildInference: true,
  columns: ['Race (player)', 'Build inference'],
  rows: [['Alice']],
  inferenceByRow: [{ playerId: 8 }, { playerId: 9 }],
}

export function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

export function emitComplete(
  onEvent: StreamHandlers['onEvent'],
  playerId: number,
  summary: string,
  diagnostics?: Record<string, unknown>
): void {
  onEvent({
    type: 'complete',
    playerId,
    status: 'exact',
    displayStatus: 'success',
    summary,
    solutionCount: 1,
    isComplete: true,
    ...(diagnostics != null ? { diagnostics } : {}),
  })
}

export function emitGlobalPause(
  onEvent: StreamHandlers['onEvent'],
  paused: boolean
): void {
  onEvent({ type: 'globalPause', paused } satisfies InferenceStreamEvent)
}
