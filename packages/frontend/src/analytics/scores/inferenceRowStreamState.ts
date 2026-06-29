import type { ScoresInferenceRowDetail, ScoresInferenceSolution } from '../../api/bff'
import type {
  InferenceStreamEvent,
  InferenceStreamSolutionPayload,
} from '../../api/inferenceStreamEventSchema'
import { readMilitaryScoreArithmetic } from './inferenceConstraints'

function omitNull<T>(value: T | null | undefined): T | undefined {
  return value ?? undefined
}

export function streamSolutionsToRowSolutions(
  solutions: InferenceStreamSolutionPayload[]
): ScoresInferenceSolution[] {
  return solutions.map((solution) => {
    const militaryScoreArithmetic = readMilitaryScoreArithmetic(solution.militaryScoreArithmetic)
    return {
      objectiveValue: solution.objectiveValue,
      actions: solution.actions,
      shipBuilds: solution.shipBuilds?.map((shipBuild) => ({
        comboId: shipBuild.comboId,
        label: shipBuild.label,
        count: shipBuild.count,
        hullId: omitNull(shipBuild.hullId),
        engineId: omitNull(shipBuild.engineId),
        beamId: omitNull(shipBuild.beamId),
        torpId: omitNull(shipBuild.torpId),
        beamCount: omitNull(shipBuild.beamCount),
        launcherCount: omitNull(shipBuild.launcherCount),
      })),
      ...(militaryScoreArithmetic != null
        ? { militaryScoreArithmetic }
        : {}),
    }
  })
}

export type RowStreamState = {
  heldSolutions: ScoresInferenceSolution[]
  status: string
  summary: string
  isComplete: boolean
  diagnostics: Record<string, unknown>
}

export function initialRowStreamState(): RowStreamState {
  return {
    heldSolutions: [],
    status: 'pending',
    summary: 'Build inference in progress',
    isComplete: false,
    diagnostics: {},
  }
}

function pausedSummaryFromSolutions(solutions: ScoresInferenceSolution[]): string {
  return solutions.length > 0
    ? `Paused with ${solutions.length} held solution(s)`
    : 'Build inference paused'
}

export function displayStatusForRow(
  status: string,
  solutionCount: number,
  isComplete: boolean
): ScoresInferenceRowDetail['displayStatus'] {
  if (status === 'paused') {
    return 'paused'
  }
  if (status === 'stopped') {
    return solutionCount > 0 ? 'success' : 'stopped'
  }
  if (solutionCount > 0 && !isComplete) {
    return 'success'
  }
  if (status === 'exact' || (solutionCount > 0 && isComplete)) {
    return 'success'
  }
  if (!isComplete) {
    return 'pending'
  }
  return 'failure'
}

export function rowDetailFromStreamState(
  playerId: number,
  state: RowStreamState
): ScoresInferenceRowDetail {
  const solutionCount = state.heldSolutions.length
  return {
    playerId,
    displayStatus: displayStatusForRow(state.status, solutionCount, state.isComplete),
    status: state.status,
    summary: state.summary,
    solutionCount,
    isComplete: state.isComplete,
    solutions: state.heldSolutions,
    diagnostics: state.diagnostics,
  }
}

export function pendingDetail(
  playerId: number,
  solutions: ScoresInferenceSolution[] = []
): ScoresInferenceRowDetail {
  return rowDetailFromStreamState(playerId, {
    ...initialRowStreamState(),
    heldSolutions: [...solutions],
  })
}

export function failureDetail(playerId: number, summary: string): ScoresInferenceRowDetail {
  return {
    playerId,
    displayStatus: 'failure',
    status: 'fetch_error',
    summary,
    solutionCount: 0,
    isComplete: true,
    solutions: [],
    diagnostics: {},
  }
}

export function reduceRowStreamState(
  state: RowStreamState,
  event: InferenceStreamEvent
): RowStreamState {
  if (event.type === 'globalPause') {
    if (event.paused && !state.isComplete) {
      return {
        ...state,
        status: 'paused',
        summary: pausedSummaryFromSolutions(state.heldSolutions),
      }
    }
    if (!event.paused && state.status === 'paused') {
      return {
        ...state,
        status: 'pending',
        summary: 'Build inference in progress',
      }
    }
    return state
  }

  if (event.type === 'progress') {
    if (state.isComplete) {
      return {
        ...initialRowStreamState(),
        summary: event.policyStepId
          ? `Searching (${event.policyStepId.replace(/_/g, ' ')})`
          : 'Build inference in progress',
      }
    }
    return {
      ...state,
      summary: event.policyStepId
        ? `Searching (${event.policyStepId.replace(/_/g, ' ')})`
        : 'Build inference in progress',
    }
  }

  if (event.type === 'solution') {
    if (state.isComplete) {
      return {
        ...initialRowStreamState(),
        heldSolutions: streamSolutionsToRowSolutions(event.solutions),
      }
    }
    return {
      ...state,
      heldSolutions: streamSolutionsToRowSolutions(event.solutions),
    }
  }

  if (event.type === 'complete') {
    return {
      ...state,
      status: event.status,
      summary: event.summary,
      isComplete: event.isComplete,
      diagnostics: event.diagnostics ?? {},
      ...(event.solutions != null
        ? { heldSolutions: streamSolutionsToRowSolutions(event.solutions) }
        : {}),
    }
  }

  if (event.type === 'error') {
    return {
      ...state,
      status: 'fetch_error',
      summary: event.detail,
      isComplete: true,
    }
  }

  return state
}

export function stablePlayerIdsKey(playerIds: readonly number[]): string {
  return [...playerIds].sort((left, right) => left - right).join(',')
}

export function playerIdsFromStableKey(playerIdsKey: string): number[] {
  if (playerIdsKey.length === 0) {
    return []
  }
  return playerIdsKey.split(',').map((part) => Number(part))
}
