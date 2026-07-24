import type { AnalyticItem } from '../api/bff'
import { BASE_MAP_ANALYTIC_ID } from '../analytics/mapAnalyticIds'

function filterEnabledAnalyticIds(
  enabledAnalyticIds: string[],
  analytics: AnalyticItem[],
  matches: (analytic: AnalyticItem) => boolean
): string[] {
  const matchingIds = new Set(analytics.filter(matches).map((analytic) => analytic.id))
  return enabledAnalyticIds.filter((id) => matchingIds.has(id))
}

/** User-enabled analytic ids that support tabular view. */
export function enabledTableAnalyticIds(
  enabledAnalyticIds: string[],
  analytics: AnalyticItem[]
): string[] {
  return filterEnabledAnalyticIds(enabledAnalyticIds, analytics, (analytic) => analytic.supportsTable)
}

/** User-enabled analytic ids that support map view (selectable only). */
export function enabledMapAnalyticIds(
  enabledAnalyticIds: string[],
  analytics: AnalyticItem[]
): string[] {
  return filterEnabledAnalyticIds(
    enabledAnalyticIds,
    analytics,
    (analytic) => analytic.supportsMap && analytic.id !== BASE_MAP_ANALYTIC_ID
  )
}
