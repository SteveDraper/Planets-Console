/**
 * Homeworld diagnostics BFF client (#274): layout-prior + evidence-refine timing.
 */

import { bffRequest, type AnalyticShellScope } from './bff'
import { throwBffHttpErrorFromResponse } from './bffHttpError'

export type LayoutPriorReportsResponse = {
  shell: AnalyticShellScope
  reports: Record<string, unknown>[]
  evidenceRefineReports: Record<string, unknown>[]
  evidenceRefineSummary: Record<string, unknown>
  baselineReports: Record<string, unknown>[]
  ensureFailures: Record<string, unknown>[]
}

function layoutPriorReportsQuery(scope: AnalyticShellScope): string {
  const params = new URLSearchParams({
    gameId: String(scope.gameId),
    perspective: String(scope.perspective),
    turn: String(scope.turn),
  })
  return params.toString()
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

export async function fetchLayoutPriorReports(
  scope: AnalyticShellScope
): Promise<LayoutPriorReportsResponse> {
  const path = `/bff/diagnostics/homeworld/layout-prior-reports?${layoutPriorReportsQuery(scope)}`
  const endpointLabel = 'GET /bff/diagnostics/homeworld/layout-prior-reports'
  const r = await bffRequest(path, undefined, endpointLabel)
  if (!r.ok) {
    await throwBffHttpErrorFromResponse(r, endpointLabel)
  }
  const body = (await r.json()) as {
    shell: { gameId: number | string; perspective: number; turn: number }
    reports: Record<string, unknown>[]
    evidenceRefineReports?: Record<string, unknown>[]
    evidenceRefineSummary?: Record<string, unknown>
    baselineReports?: Record<string, unknown>[]
    ensureFailures?: Record<string, unknown>[]
  }
  return {
    shell: normalizeShell(body.shell),
    reports: body.reports ?? [],
    evidenceRefineReports: body.evidenceRefineReports ?? [],
    evidenceRefineSummary: body.evidenceRefineSummary ?? {},
    baselineReports: body.baselineReports ?? [],
    ensureFailures: body.ensureFailures ?? [],
  }
}
