import type { ScoresInferenceRowDetail, ScoresInferenceSolution } from '../../api/bff'
import type {
  InferenceDisplayStatus,
  InferenceStreamEvent,
  InferenceStreamSolutionPayload,
  FleetTorpInputStatus,
  LatticeSignature,
  UnknownLossLeftover,
} from '../../api/inferenceStreamEventSchema'
import {
  analyticFreshnessForPhase,
  freshnessPhaseAfterAbsentSignal,
  freshnessPhaseAfterAccept,
  phaseForStoredEvidence,
  type AnalyticFreshness,
  type AnalyticFreshnessPhase,
} from '../analyticFreshness'
import { readMilitaryScoreArithmetic } from './inferenceConstraints'

function omitNull<T>(value: T | null | undefined): T | undefined {
  return value ?? undefined
}

export function pointUnexplainedMilitaryDelta2x(
  leftover: UnknownLossLeftover | undefined,
  unexplainedMilitaryDelta2x: number | undefined
): number | undefined {
  if (leftover?.kind === 'unknown_loss_bound') {
    return undefined
  }
  return unexplainedMilitaryDelta2x
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
      ...(solution.shipFirstFamily != null
        ? { shipFirstFamily: solution.shipFirstFamily }
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
  placeholders: Record<string, unknown>[]
  displayStatus?: InferenceDisplayStatus
  leftover?: UnknownLossLeftover
  latticeSignatures?: LatticeSignature[]
  unexplainedMilitaryDelta2x?: number
  fleetTorpInputStatus?: FleetTorpInputStatus
  fleetTorpOverlayBeliefSetTorpIds?: number[]
  freshnessPhase: AnalyticFreshnessPhase
  hasStoredRow: boolean
  evidenceGeneration: number | null
  evidenceMark: number | null
  /** Real complete or error. A stored paint does not settle the run. */
  isStreamSettled: boolean
}

export function initialRowStreamState(): RowStreamState {
  return {
    heldSolutions: [],
    status: 'pending',
    summary: 'Build inference in progress',
    isComplete: false,
    diagnostics: {},
    placeholders: [],
    freshnessPhase: 'unlabeled',
    hasStoredRow: false,
    evidenceGeneration: null,
    evidenceMark: null,
    isStreamSettled: false,
  }
}

/** The run has a real complete or error. A stored paint leaves it open. */
export function isRowStreamSettled(state: RowStreamState): boolean {
  return state.isStreamSettled
}

function pausedSummaryFromSolutions(solutions: ScoresInferenceSolution[]): string {
  return solutions.length > 0
    ? `Paused with ${solutions.length} held solution(s)`
    : 'Build inference paused'
}

function inFlightDisplayStatus(state: RowStreamState): InferenceDisplayStatus {
  if (state.status === 'paused') {
    return 'paused'
  }
  if (state.heldSolutions.length > 0) {
    return 'success'
  }
  if (!state.isComplete) {
    return 'pending'
  }
  return 'failure'
}

function freshnessForRow(state: RowStreamState): AnalyticFreshness {
  return analyticFreshnessForPhase(state.freshnessPhase)
}

function searchingSummary(policyStepId: string | undefined): string {
  return policyStepId
    ? `Searching (${policyStepId.replace(/_/g, ' ')})`
    : 'Build inference in progress'
}

function busyStoredRow(
  state: RowStreamState,
  summary: string,
  patch: Partial<RowStreamState> = {}
): RowStreamState {
  return {
    ...state,
    ...patch,
    isComplete: false,
    isStreamSettled: false,
    status: 'pending',
    summary,
    displayStatus: 'pending',
  }
}

function freshnessField(freshness: AnalyticFreshness): Pick<ScoresInferenceRowDetail, 'freshness'> {
  if (freshness === 'none') {
    return {}
  }
  return { freshness }
}

export function rowDetailFromStreamState(
  playerId: number,
  state: RowStreamState
): ScoresInferenceRowDetail {
  const solutionCount = state.heldSolutions.length
  const unexplainedMilitaryDelta2x = pointUnexplainedMilitaryDelta2x(
    state.leftover,
    state.unexplainedMilitaryDelta2x
  )
  return {
    playerId,
    displayStatus: state.displayStatus ?? inFlightDisplayStatus(state),
    status: state.status,
    summary: state.summary,
    solutionCount,
    isComplete: state.isComplete,
    solutions: state.heldSolutions,
    diagnostics: state.diagnostics,
    placeholders: state.placeholders,
    ...(state.leftover != null ? { leftover: state.leftover } : {}),
    ...(state.latticeSignatures != null ? { latticeSignatures: state.latticeSignatures } : {}),
    ...(unexplainedMilitaryDelta2x != null ? { unexplainedMilitaryDelta2x } : {}),
    ...(state.fleetTorpInputStatus != null
      ? { fleetTorpInputStatus: state.fleetTorpInputStatus }
      : {}),
    ...(state.fleetTorpOverlayBeliefSetTorpIds != null
      ? { fleetTorpOverlayBeliefSetTorpIds: state.fleetTorpOverlayBeliefSetTorpIds }
      : {}),
    ...freshnessField(freshnessForRow(state)),
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
    placeholders: [],
  }
}

type ScoreboardPaintEvent = Extract<InferenceStreamEvent, { type: 'complete' | 'stored_row' }>

function fleetTorpFieldsFromPaint(
  event: ScoreboardPaintEvent
): Pick<RowStreamState, 'fleetTorpInputStatus' | 'fleetTorpOverlayBeliefSetTorpIds'> {
  const fields: Pick<RowStreamState, 'fleetTorpInputStatus' | 'fleetTorpOverlayBeliefSetTorpIds'> =
    {}
  if (event.fleetTorpInputStatus != null) {
    fields.fleetTorpInputStatus = event.fleetTorpInputStatus
  }
  if (event.fleetTorpOverlayBeliefSetTorpIds != null) {
    fields.fleetTorpOverlayBeliefSetTorpIds = event.fleetTorpOverlayBeliefSetTorpIds
  }
  return fields
}

function applyScoreboardPaint(
  state: RowStreamState,
  event: ScoreboardPaintEvent
): RowStreamState {
  const hasStoredRow =
    event.type === 'stored_row' || event.evidenceGeneration != null || state.hasStoredRow
  const evidenceGeneration =
    event.evidenceGeneration != null ? event.evidenceGeneration : state.evidenceGeneration
  const evidenceMark = event.evidenceMark != null ? event.evidenceMark : state.evidenceMark
  return {
    ...state,
    freshnessPhase: hasStoredRow
      ? phaseForStoredEvidence(evidenceGeneration, evidenceMark)
      : 'current',
    hasStoredRow,
    evidenceGeneration,
    evidenceMark,
    status: event.status,
    displayStatus: event.displayStatus,
    summary: event.summary,
    isComplete: event.isComplete,
    isStreamSettled: event.type === 'complete',
    diagnostics: event.diagnostics ?? {},
    placeholders: event.placeholders ?? [],
    ...(event.leftover != null ? { leftover: event.leftover } : {}),
    ...(event.latticeSignatures != null
      ? { latticeSignatures: event.latticeSignatures }
      : {}),
    unexplainedMilitaryDelta2x: pointUnexplainedMilitaryDelta2x(
      event.leftover ?? state.leftover,
      event.unexplainedMilitaryDelta2x ?? state.unexplainedMilitaryDelta2x
    ),
    ...fleetTorpFieldsFromPaint(event),
    ...(event.solutions != null
      ? { heldSolutions: streamSolutionsToRowSolutions(event.solutions) }
      : {}),
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

  if (event.type === 'no_stored_row') {
    const freshnessPhase = freshnessPhaseAfterAbsentSignal(state.freshnessPhase)
    if (freshnessPhase === state.freshnessPhase) {
      return state
    }
    return {
      ...state,
      freshnessPhase,
    }
  }

  if (event.type === 'work_accepted') {
    if (state.hasStoredRow) {
      return busyStoredRow(state, 'Build inference in progress')
    }
    return {
      ...initialRowStreamState(),
      freshnessPhase: freshnessPhaseAfterAccept(state.freshnessPhase, false),
      heldSolutions: state.heldSolutions,
    }
  }

  if (event.type === 'progress') {
    const summary = searchingSummary(event.policyStepId)
    if (state.isComplete && state.hasStoredRow) {
      return busyStoredRow(state, summary)
    }
    if (state.isComplete) {
      return {
        ...initialRowStreamState(),
        freshnessPhase: 'current',
        summary,
      }
    }
    return {
      ...state,
      summary,
    }
  }

  if (event.type === 'solution') {
    const fleetTorpInputStatus =
      event.fleetTorpInputStatus != null
        ? { fleetTorpInputStatus: event.fleetTorpInputStatus }
        : {}
    const heldSolutions = streamSolutionsToRowSolutions(event.solutions)
    if (state.isComplete && state.hasStoredRow) {
      return busyStoredRow(state, 'Build inference in progress', {
        heldSolutions,
        ...fleetTorpInputStatus,
      })
    }
    if (state.isComplete) {
      return {
        ...initialRowStreamState(),
        freshnessPhase: 'current',
        heldSolutions,
        ...fleetTorpInputStatus,
      }
    }
    return {
      ...state,
      heldSolutions,
      ...fleetTorpInputStatus,
    }
  }

  if (event.type === 'complete' || event.type === 'stored_row') {
    return applyScoreboardPaint(state, event)
  }

  if (event.type === 'error') {
    return {
      ...state,
      status: 'fetch_error',
      displayStatus: 'failure',
      summary: event.detail,
      isComplete: true,
      isStreamSettled: true,
    }
  }

  return state
}

