/**
 * Compute-diagnostics BFF client: freeze status, snapshot, freeze, allowlist, and single-step.
 */

import {
  bffRequest,
  withEndpointIfGeneric,
  type AnalyticShellScope,
} from './bff'

export type ComputeDiagnosticsFreezeStatusResponse = {
  shell: AnalyticShellScope
  freezeArmed: boolean
  allowlistedPlayerIds: number[]
}

export type NextSingleStepTarget = {
  scopeKey: string
  analyticId: string
  stepKind: string | null
  stepIndex: number
  priorityBand: string | null
  backend: string | null
  source: 'held' | 'would_dispatch'
  /** Pool registration id when the preview is bound to a specific orchestrator. */
  orchestratorId?: number | null
}

export type NextSingleStepPreview = {
  target: NextSingleStepTarget | null
  disabledReason:
    | 'freeze_not_armed'
    | 'empty_allowlist'
    | 'nothing_steppable'
    | 'work_in_progress'
    | null
}

export type RemotePoolBackendProbe = {
  maxWorkers: number | null
  queueDepth: number | null
  counts: {
    pending: number
    running: number
    done: number
    cancelled: number
  }
  futures: Record<string, unknown>[]
}

export type ComputeDiagnosticsLiveOccupancy = {
  configuredWorkers: number
  scopedReadyDepth: number
  scopedInFlightCount: number
  globalInFlightCount: number
  globalQueueDepth: number
  backendMix: Record<string, number>
}

export type ComputeDiagnosticsConcurrencyRollup = {
  eventCount: number
  uniquePlayers: number[]
  backendHistogram: Record<string, number>
  durationByBackendMs: Record<string, Record<string, number | null>>
  scopedReadyDepth: Record<string, number | null>
  scopedInFlight: Record<string, number | null>
  globalInFlight: Record<string, number | null>
  maxScopedReadyDepth: number
  maxScopedInFlight: number
  maxGlobalInFlight: number
  configuredWorkers: number | null
}

export type ComputeDiagnosticsSnapshotResponse = {
  shell: AnalyticShellScope
  freezeArmed: boolean
  allowlistedPlayerIds: number[]
  poolQueue: Record<string, unknown>[]
  inFlight: Record<string, unknown>[]
  dagNodes: Record<string, unknown>[]
  readyQueue: Record<string, unknown>[]
  nextSingleStep: NextSingleStepPreview
  completionHistory: Record<string, unknown>[]
  serverStreams: Record<string, unknown>[]
  remotePool: {
    interpreter: RemotePoolBackendProbe
    process: RemotePoolBackendProbe
  }
  liveOccupancy: ComputeDiagnosticsLiveOccupancy
  concurrencyTimeline: Record<string, unknown>[]
  concurrencyRollup: ComputeDiagnosticsConcurrencyRollup
}

function normalizeShell(shell: {
  gameId: number | string
  perspective: number
  turn: number
}): AnalyticShellScope {
  return {
    gameId: String(shell.gameId),
    perspective: shell.perspective,
    turn: shell.turn,
  }
}

function computeDiagnosticsQuery(scope: AnalyticShellScope): string {
  const params = new URLSearchParams({
    gameId: String(scope.gameId),
    perspective: String(scope.perspective),
    turn: String(scope.turn),
  })
  return params.toString()
}

export async function fetchComputeDiagnosticsFreezeStatus(
  scope: AnalyticShellScope
): Promise<ComputeDiagnosticsFreezeStatusResponse> {
  const path = `/bff/diagnostics/compute/freeze-status?${computeDiagnosticsQuery(scope)}`
  const endpointLabel = 'GET /bff/diagnostics/compute/freeze-status'
  const r = await bffRequest(path, undefined, endpointLabel)
  if (!r.ok) {
    throw new Error(withEndpointIfGeneric(String(r.status), endpointLabel))
  }
  const body = (await r.json()) as {
    shell: { gameId: number | string; perspective: number; turn: number }
    freezeArmed: boolean
    allowlistedPlayerIds: number[]
  }
  return {
    shell: normalizeShell(body.shell),
    freezeArmed: body.freezeArmed,
    allowlistedPlayerIds: body.allowlistedPlayerIds,
  }
}

export async function fetchComputeDiagnosticsSnapshot(
  scope: AnalyticShellScope
): Promise<ComputeDiagnosticsSnapshotResponse> {
  const path = `/bff/diagnostics/compute/snapshot?${computeDiagnosticsQuery(scope)}`
  const endpointLabel = 'GET /bff/diagnostics/compute/snapshot'
  const r = await bffRequest(path, undefined, endpointLabel)
  return readSnapshotResponse(r, endpointLabel)
}

async function readSnapshotResponse(
  r: Response,
  endpointLabel: string
): Promise<ComputeDiagnosticsSnapshotResponse> {
  if (!r.ok) {
    throw new Error(withEndpointIfGeneric(String(r.status), endpointLabel))
  }
  const body = (await r.json()) as ComputeDiagnosticsSnapshotResponse & {
    shell: { gameId: number | string; perspective: number; turn: number }
  }
  return {
    ...body,
    shell: normalizeShell(body.shell),
  }
}

export async function putComputeDiagnosticsFreeze(
  scope: AnalyticShellScope,
  freezeArmed: boolean
): Promise<ComputeDiagnosticsSnapshotResponse> {
  const path = '/bff/diagnostics/compute/freeze'
  const endpointLabel = 'PUT /bff/diagnostics/compute/freeze'
  const r = await bffRequest(
    path,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        gameId: scope.gameId,
        perspective: scope.perspective,
        turn: scope.turn,
        freezeArmed,
      }),
    },
    endpointLabel
  )
  return readSnapshotResponse(r, endpointLabel)
}

export async function putComputeDiagnosticsAllowlist(
  scope: AnalyticShellScope,
  playerIds: number[]
): Promise<ComputeDiagnosticsSnapshotResponse> {
  const path = '/bff/diagnostics/compute/allowlist'
  const endpointLabel = 'PUT /bff/diagnostics/compute/allowlist'
  const r = await bffRequest(
    path,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        gameId: scope.gameId,
        perspective: scope.perspective,
        turn: scope.turn,
        playerIds,
      }),
    },
    endpointLabel
  )
  return readSnapshotResponse(r, endpointLabel)
}

export async function postComputeDiagnosticsSingleStep(
  scope: AnalyticShellScope
): Promise<ComputeDiagnosticsSnapshotResponse> {
  const path = '/bff/diagnostics/compute/single-step'
  const endpointLabel = 'POST /bff/diagnostics/compute/single-step'
  const r = await bffRequest(
    path,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        gameId: scope.gameId,
        perspective: scope.perspective,
        turn: scope.turn,
      }),
    },
    endpointLabel
  )
  return readSnapshotResponse(r, endpointLabel)
}
