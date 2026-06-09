import type { ScoresInferenceRowDetail } from '../../api/bff'

export type InferenceDisplayStatus = ScoresInferenceRowDetail['displayStatus']

export function inferenceAccessibleLabel(detail: ScoresInferenceRowDetail): string {
  if (detail.displayStatus === 'success') {
    if (!detail.isComplete && detail.solutionCount > 0) {
      return `${detail.summary || 'Held explanations'}; search continuing`
    }
    return detail.summary || 'Feasible build explanation found'
  }
  if (detail.displayStatus === 'pending') {
    return detail.summary || 'Build inference in progress'
  }
  if (detail.displayStatus === 'paused') {
    return detail.summary || 'Build inference paused'
  }
  if (detail.displayStatus === 'stopped') {
    return detail.summary || 'Build inference halted'
  }
  return detail.summary || 'No build inference result'
}

export function canOpenInferenceDetail(detail: ScoresInferenceRowDetail): boolean {
  return (
    (detail.displayStatus === 'success' || detail.displayStatus === 'paused') &&
    detail.solutionCount > 0
  )
}

export function isIncompleteInferenceRow(detail: ScoresInferenceRowDetail): boolean {
  if (detail.isComplete) {
    return false
  }
  return (
    detail.displayStatus === 'pending' ||
    detail.displayStatus === 'paused' ||
    detail.displayStatus === 'success'
  )
}

export function isActivelySearchingInference(
  detail: ScoresInferenceRowDetail,
  isGloballyPaused = false
): boolean {
  if (detail.isComplete || isGloballyPaused || detail.displayStatus === 'paused') {
    return false
  }
  if (
    detail.solutionCount === 0 &&
    detail.diagnostics?.streamInterimSegmentProgress === true
  ) {
    return false
  }
  return detail.displayStatus === 'pending' || detail.displayStatus === 'success'
}
