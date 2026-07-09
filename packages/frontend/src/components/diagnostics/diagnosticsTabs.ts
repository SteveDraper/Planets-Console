export const DIAGNOSTICS_TAB_IDS = ['requests', 'scores', 'compute'] as const

export type DiagnosticsTabId = (typeof DIAGNOSTICS_TAB_IDS)[number]

export const DIAGNOSTICS_TAB_LABELS: Record<DiagnosticsTabId, string> = {
  requests: 'Requests',
  scores: 'Scores',
  compute: 'Compute',
}

export const DIAGNOSTICS_TAB_IDS_WITHOUT_COMPUTE = ['requests', 'scores'] as const

export type DiagnosticsTabIdWithoutCompute = (typeof DIAGNOSTICS_TAB_IDS_WITHOUT_COMPUTE)[number]
