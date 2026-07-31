import {
  bffRequest,
  type AnalyticShellScope,
} from '../../api/bff'
import { throwBffHttpErrorFromResponse } from '../../api/bffHttpError'
import { HOMEWORLD_LOCATOR_ANALYTIC_ID } from './constants'
import {
  parseHomeworldLocatorPayload,
  type HomeworldLocatorPayload,
} from './wireSchema'

function homeworldScopeQuery(scope: AnalyticShellScope): string {
  const params = new URLSearchParams({
    gameId: scope.gameId,
    turn: String(scope.turn),
    perspective: String(scope.perspective),
  })
  const username = scope.username?.trim()
  if (username) {
    params.set('username', username)
  }
  return `?${params.toString()}`
}

async function fetchHomeworldLocator(
  view: 'table' | 'map',
  scope: AnalyticShellScope
): Promise<HomeworldLocatorPayload> {
  const path = `/bff/analytics/${encodeURIComponent(HOMEWORLD_LOCATOR_ANALYTIC_ID)}/${view}`
  const qs = homeworldScopeQuery(scope)
  const endpointLabel = `GET ${path}`
  const response = await bffRequest(`${path}${qs}`, { cache: 'no-store' }, endpointLabel)
  if (!response.ok) {
    await throwBffHttpErrorFromResponse(response, endpointLabel)
  }
  const raw: unknown = await response.json()
  const parsed = parseHomeworldLocatorPayload(raw)
  if (parsed == null) {
    throw new Error(`${endpointLabel}: invalid homeworld locator payload`)
  }
  return parsed
}

export function fetchHomeworldLocatorTable(
  scope: AnalyticShellScope
): Promise<HomeworldLocatorPayload> {
  return fetchHomeworldLocator('table', scope)
}

export function fetchHomeworldLocatorMap(
  scope: AnalyticShellScope
): Promise<HomeworldLocatorPayload> {
  return fetchHomeworldLocator('map', scope)
}
