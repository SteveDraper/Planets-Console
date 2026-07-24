import type { AnalyticItem } from '../api/bff'

/** User-enabled analytic ids that support tabular view. */
export function enabledTableAnalyticIds(
  enabledAnalyticIds: string[],
  analytics: AnalyticItem[]
): string[] {
  const tableSupportedIds = new Set(
    analytics.filter((analytic) => analytic.supportsTable).map((analytic) => analytic.id)
  )
  return enabledAnalyticIds.filter((id) => tableSupportedIds.has(id))
}
