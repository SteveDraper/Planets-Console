/**
 * Compute-diagnostics BFF client: snapshot, freeze, allowlist, and single-step.
 */

import {
  bffRequest,
  withEndpointIfGeneric,
  type AnalyticShellScope,
} from './bff'

export type ComputeDiagnosticsSnapshotResponse = {
  shell: AnalyticShellScope
  freezeArmed: boolean
  allowlistedPlayerIds: number[]
  poolQueue: Record<string, unknown>[]
  dagNodes: Record<string, unknown>[]
  readyQueue: Record<string, unknown>[]
  completionHistory: Record<string, unknown>[]
  serverStreams: Record<string, unknown>[]
}

function computeDiagnosticsQuery(scope: AnalyticShellScope): string {
  const params = new URLSearchParams({
    gameId: String(scope.gameId),
    perspective: String(scope.perspective),
    turn: String(scope.turn),
  })
  return params.toString()
}

export async function fetchComputeDiagnosticsSnapshot(
  scope: AnalyticShellScope
): Promise<ComputeDiagnosticsSnapshotResponse> {
  const path = `/bff/diagnostics/compute/snapshot?${computeDiagnosticsQuery(scope)}`
  const endpointLabel = 'GET /bff/diagnostics/compute/snapshot'
  const r = await bffRequest(path, undefined, endpointLabel)
  if (!r.ok) {
    throw new Error(withEndpointIfGeneric(String(r.status), endpointLabel))
  }
  return r.json()
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
  if (!r.ok) {
    throw new Error(withEndpointIfGeneric(String(r.status), endpointLabel))
  }
  return r.json()
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
  if (!r.ok) {
    throw new Error(withEndpointIfGeneric(String(r.status), endpointLabel))
  }
  return r.json()
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
  if (!r.ok) {
    throw new Error(withEndpointIfGeneric(String(r.status), endpointLabel))
  }
  return r.json()
}
