import {
  bffRequest,
  type AnalyticShellScope,
} from '../../api/bff'
import { throwBffHttpErrorFromResponse } from '../../api/bffHttpError'
import type { components } from '../../api/schema-analytics'
import { HOMEWORLD_LOCATOR_ANALYTIC_ID } from './constants'
import {
  parseHomeworldLocatorPayload,
  type HomeworldLocatorPayload,
} from './wireSchema'

export type HomeworldAssertionRequest =
  components['schemas']['HomeworldAssertionRequest']

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

async function parseHomeworldMutationResponse(
  response: Response,
  endpointLabel: string
): Promise<HomeworldLocatorPayload> {
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

/** Upsert or revoke a location/ownership homeworld assertion. */
export async function postHomeworldLocatorAssertion(
  scope: AnalyticShellScope,
  body: HomeworldAssertionRequest
): Promise<HomeworldLocatorPayload> {
  const path = `/bff/analytics/${encodeURIComponent(HOMEWORLD_LOCATOR_ANALYTIC_ID)}/assertions`
  const qs = homeworldScopeQuery(scope)
  const endpointLabel = `POST ${path}`
  const response = await bffRequest(
    `${path}${qs}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
    endpointLabel
  )
  return parseHomeworldMutationResponse(response, endpointLabel)
}

/** Wipe machine homeworld state and rebuild via ensure (asserts preserved). */
export async function postHomeworldLocatorRefresh(
  scope: AnalyticShellScope
): Promise<HomeworldLocatorPayload> {
  const path = `/bff/analytics/${encodeURIComponent(HOMEWORLD_LOCATOR_ANALYTIC_ID)}/refresh`
  const qs = homeworldScopeQuery(scope)
  const endpointLabel = `POST ${path}`
  const response = await bffRequest(
    `${path}${qs}`,
    { method: 'POST' },
    endpointLabel
  )
  return parseHomeworldMutationResponse(response, endpointLabel)
}
