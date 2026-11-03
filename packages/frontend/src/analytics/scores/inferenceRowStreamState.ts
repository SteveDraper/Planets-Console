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
  freshnessAfterAbsent,
  freshnessAfterAccept,
  freshnessAfterCurrentPaint,
  freshnessAfterStoredPaint,
  initialFreshnessState,
  type AnalyticFreshness,
  type FreshnessState,
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
  freshness: FreshnessState
  /** Real complete or error. A stored paint does not settle the run. */
  isStreamSettled: boolean
}

const BUILD_INFERENCE_IN_PROGRESS_SUMMARY = 'Build inference in progress'

export function initialRowStreamState(): RowStreamState {
  return {
    heldSolutions: [],
    status: 'pending',
    summary: BUILD_INFERENCE_IN_PROGRESS_SUMMARY,
    isComplete: false,
    diagnostics: {},
    placeholders: [],
    freshness: initialFreshnessState(),
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
  return analyticFreshnessForPhase(state.freshness.phase)
}

function searchingSummary(policyStepId: string | undefined): string {
  return policyStepId
    ? `Searching (${policyStepId.replace(/_/g, ' ')})`
    : BUILD_INFERENCE_IN_PROGRESS_SUMMARY
}

type RowRunUpdate = Partial<
  Pick<RowStreamState, 'heldSolutions' | 'summary' | 'fleetTorpInputStatus'>
>

type RowRunActivity = {
  restart: 'always' | 'when-complete'
  summary: string
  updates: RowRunUpdate
}

/**
 * A restart keeps a stored row and shows it as pending.
 * With nothing stored, the row is replaced by a fresh current row.
 * An open run that is not restarting only applies the event updates.
 */
function rowForRunActivity(state: RowStreamState, activity: RowRunActivity): RowStreamState {
  const restarting = activity.restart === 'always' || state.isComplete
  if (!restarting) {
    return { ...state, ...activity.updates }
  }
  if (state.freshness.hasStoredRow) {
    return {
      ...state,
      ...activity.updates,
      isComplete: false,
      isStreamSettled: false,
      status: 'pending',
      displayStatus: 'pending',
      summary: activity.summary,
    }
  }
  return {
    ...initialRowStreamState(),
    ...activity.updates,
    freshness: freshnessAfterAccept(initialFreshnessState()),
    summary: activity.summary,
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

function scoreboardPaintIsStored(freshness: FreshnessState, event: ScoreboardPaintEvent): boolean {
  return event.type === 'stored_row' || event.evidenceGeneration != null || freshness.hasStoredRow
}

function applyScoreboardPaint(
  state: RowStreamState,
  event: ScoreboardPaintEvent
): RowStreamState {
  const freshness = scoreboardPaintIsStored(state.freshness, event)
    ? freshnessAfterStoredPaint(state.freshness, event)
    : freshnessAfterCurrentPaint(state.freshness, event)
  return {
    ...state,
    freshness,
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
        summary: BUILD_INFERENCE_IN_PROGRESS_SUMMARY,
      }
    }
    return state
  }

  if (event.type === 'no_stored_row') {
    const freshness = freshnessAfterAbsent(state.freshness)
    if (freshness === state.freshness) {
      return state
    }
    return {
      ...state,
      freshness,
    }
  }

  if (event.type === 'work_accepted') {
    return rowForRunActivity(state, {
      restart: 'always',
      summary: BUILD_INFERENCE_IN_PROGRESS_SUMMARY,
      updates: { heldSolutions: state.heldSolutions },
    })
  }

  if (event.type === 'progress') {
    const summary = searchingSummary(event.policyStepId)
    return rowForRunActivity(state, {
      restart: 'when-complete',
      summary,
      updates: { summary },
    })
  }

  if (event.type === 'solution') {
    const fleetTorpInputStatus =
      event.fleetTorpInputStatus != null
        ? { fleetTorpInputStatus: event.fleetTorpInputStatus }
        : {}
    return rowForRunActivity(state, {
      restart: 'when-complete',
      summary: BUILD_INFERENCE_IN_PROGRESS_SUMMARY,
      updates: {
        heldSolutions: streamSolutionsToRowSolutions(event.solutions),
        ...fleetTorpInputStatus,
      },
    })
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

