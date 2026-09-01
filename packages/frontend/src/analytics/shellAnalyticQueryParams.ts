import { CONNECTIONS_ANALYTIC_ID } from './mapAnalyticIds'
import { appendConnectionsMapQueryParamsFromStore } from './connections/queryParams'
import { SCORES_ANALYTIC_ID } from './scores/api'
import { appendScoresTableQueryParamsFromStore } from './scores/queryParams'

export type ShellAnalyticQueryParamAdapters = {
  appendTable?: (params: URLSearchParams) => void
  appendMap?: (params: URLSearchParams) => void
}

/**
 * React-free lookup of query-param adapters for generic table/map fetch.
 * This is the only write site for appender functions; `shellAnalyticRegistry.ts`
 * composes the same references onto `queryParams`. `bff.ts` imports this module
 * so it does not pull sidebar/table React chrome.
 */
export const SHELL_TABLE_QUERY_APPENDERS: Record<string, (params: URLSearchParams) => void> = {
  [SCORES_ANALYTIC_ID]: appendScoresTableQueryParamsFromStore,
}

export const SHELL_MAP_QUERY_APPENDERS: Record<string, (params: URLSearchParams) => void> = {
  [CONNECTIONS_ANALYTIC_ID]: appendConnectionsMapQueryParamsFromStore,
}

export function queryParamsAdaptersFor(
  analyticId: string
): ShellAnalyticQueryParamAdapters | undefined {
  const appendTable = SHELL_TABLE_QUERY_APPENDERS[analyticId]
  const appendMap = SHELL_MAP_QUERY_APPENDERS[analyticId]
  if (appendTable == null && appendMap == null) {
    return undefined
  }
  return {
    ...(appendTable != null ? { appendTable } : {}),
    ...(appendMap != null ? { appendMap } : {}),
  }
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
