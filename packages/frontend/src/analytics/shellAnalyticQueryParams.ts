import { CONNECTIONS_ANALYTIC_ID } from './mapAnalyticIds'
import { appendConnectionsMapQueryParamsFromStore } from './connections/queryParams'
import { SCORES_ANALYTIC_ID } from './scores/api'
import { appendScoresTableQueryParamsFromStore } from './scores/queryParams'

/**
 * React-free lookup of query-param adapters for generic table/map fetch.
 * Same functions as `queryParams` on the shell registration; `bff.ts` imports
 * this module so it does not pull sidebar/table React chrome.
 */
export const SHELL_TABLE_QUERY_APPENDERS: Record<string, (params: URLSearchParams) => void> = {
  [SCORES_ANALYTIC_ID]: appendScoresTableQueryParamsFromStore,
}

export const SHELL_MAP_QUERY_APPENDERS: Record<string, (params: URLSearchParams) => void> = {
  [CONNECTIONS_ANALYTIC_ID]: appendConnectionsMapQueryParamsFromStore,
}

export function appendRegisteredTableQueryParams(
  analyticId: string,
  params: URLSearchParams
): void {
  SHELL_TABLE_QUERY_APPENDERS[analyticId]?.(params)
}

export function appendRegisteredMapQueryParams(
  analyticId: string,
  params: URLSearchParams
): void {
  SHELL_MAP_QUERY_APPENDERS[analyticId]?.(params)
}
