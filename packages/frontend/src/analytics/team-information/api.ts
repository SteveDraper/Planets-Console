import { bffRequest, type AnalyticShellScope, type MapDataResponse } from '../../api/bff'
import { throwBffHttpErrorFromResponse } from '../../api/bffHttpError'
import { normalizeMapRegionOverlays } from '../../api/normalizeMapRegionOverlay'
import { TEAM_INFORMATION_ANALYTIC_ID } from '../mapAnalyticIds'
import {
  parseTeamInformationPayload,
  type TeamInformationPayload,
} from './wireSchema'

function teamInformationScopeQuery(scope: AnalyticShellScope): string {
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

export function teamInformationMapDataResponse(
  payload: TeamInformationPayload
): MapDataResponse {
  return {
    analyticId: payload.analyticId,
    nodes: [],
    edges: [],
    regionOverlays: normalizeMapRegionOverlays(payload.regionOverlays),
    teamInformationTeams: payload.teams,
  }
}

/** Map GET for team information. Scope params only; no analytic query parameter. */
export async function fetchTeamInformationMap(
  scope: AnalyticShellScope
): Promise<MapDataResponse> {
  const path = `/bff/analytics/${encodeURIComponent(TEAM_INFORMATION_ANALYTIC_ID)}/map`
  const endpointLabel = `GET ${path}`
  const response = await bffRequest(
    `${path}${teamInformationScopeQuery(scope)}`,
    { cache: 'no-store' },
    endpointLabel
  )
  if (!response.ok) {
    await throwBffHttpErrorFromResponse(response, endpointLabel)
  }
  const raw: unknown = await response.json()
  const parsed = parseTeamInformationPayload(raw)
  if (parsed == null) {
    throw new Error(`${endpointLabel}: invalid team information payload`)
  }
  return teamInformationMapDataResponse(parsed)
}
