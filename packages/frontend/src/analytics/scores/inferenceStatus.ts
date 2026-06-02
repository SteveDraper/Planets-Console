import type { ScoresInferenceRowDetail } from '../../api/bff'

export type InferenceDisplayStatus = ScoresInferenceRowDetail['displayStatus']

export function inferenceAccessibleLabel(detail: ScoresInferenceRowDetail): string {
  if (detail.displayStatus === 'success') {
    return detail.summary || 'Feasible build explanation found'
  }
  if (detail.displayStatus === 'pending') {
    return detail.summary || 'Build inference in progress'
  }
  return detail.summary || 'No build inference result'
}

export function canOpenInferenceDetail(detail: ScoresInferenceRowDetail): boolean {
  return detail.displayStatus === 'success' && detail.solutionCount > 0
}
