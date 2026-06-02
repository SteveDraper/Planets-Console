export const DIAGNOSTICS_TAB_IDS = ['requests', 'scores'] as const

export type DiagnosticsTabId = (typeof DIAGNOSTICS_TAB_IDS)[number]

export const DIAGNOSTICS_TAB_LABELS: Record<DiagnosticsTabId, string> = {
  requests: 'Requests',
  scores: 'Scores',
}
