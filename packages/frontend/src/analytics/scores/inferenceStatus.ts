import type { ScoresInferenceRowDetail } from '../../api/bff'
import {
  fleetTorpInputAccessibleLabel,
  fleetTorpInputAppendsToInferenceAccessibleLabel,
  readFleetTorpInputStatusFromDetail,
} from './fleetTorpInputStatus'

export type InferenceDisplayStatus = ScoresInferenceRowDetail['displayStatus']

function baseInferenceAccessibleLabel(detail: ScoresInferenceRowDetail): string {
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

function combineInferenceAccessibleLabel(
  inferenceLabel: string,
  detail: ScoresInferenceRowDetail
): string {
  const fleetStatus = readFleetTorpInputStatusFromDetail(detail)
  if (fleetStatus == null || !fleetTorpInputAppendsToInferenceAccessibleLabel(fleetStatus)) {
    return inferenceLabel
  }
  return `${inferenceLabel}. ${fleetTorpInputAccessibleLabel(fleetStatus)}`
}

export function inferenceAccessibleLabel(detail: ScoresInferenceRowDetail): string {
  return combineInferenceAccessibleLabel(baseInferenceAccessibleLabel(detail), detail)
}

export function canOpenInferenceDetail(detail: ScoresInferenceRowDetail): boolean {
  if (
    (detail.displayStatus === 'success' || detail.displayStatus === 'paused') &&
    detail.solutionCount > 0
  ) {
    return true
  }
  return (
    detail.isComplete &&
    (detail.displayStatus === 'failure' || detail.displayStatus === 'stopped')
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
  return detail.displayStatus === 'pending' || detail.displayStatus === 'success'
}
