/** How flare-assisted routes are requested from Core (`flareMode` query). */
export type ConnectionsFlareMode = 'off' | 'include' | 'only'

/**
 * Max **hops** (1-3) for Core's mixed **normal-move + flare** reachability test.
 * Each hop is one normal well move or one flare, and a valid path must use at least one flare.
 */
export type ConnectionsFlareDepth = 1 | 2 | 3

/**
 * Wire query names for Connections map GETs.
 * Keep in sync with `api.transport.connections_options` in Core.
 */
export const CONNECTIONS_QUERY_WIRE = {
  warpSpeed: 'warpSpeed',
  gravitonicMovement: 'gravitonicMovement',
  flareMode: 'flareMode',
  flareDepth: 'flareDepth',
  includeIllustrativeRoutes: 'includeIllustrativeRoutes',
} as const

/** Query parameters for the Connections map analytic (BFF forwards to Core). */
export type ConnectionsMapParams = {
  warpSpeed: number
  gravitonicMovement: boolean
  flareMode: ConnectionsFlareMode
  flareDepth: ConnectionsFlareDepth
}

/** Must match `api.transport.connections_options.derive_include_illustrative_routes`. */
export function deriveIncludeIllustrativeRoutes(
  flareMode: ConnectionsFlareMode,
  flareDepth: number
): boolean {
  return flareMode !== 'off' && flareDepth >= 2
}

export function appendConnectionsMapQueryParams(
  params: URLSearchParams,
  connectionsParams: ConnectionsMapParams
): void {
  const wire = CONNECTIONS_QUERY_WIRE
  params.set(wire.warpSpeed, String(connectionsParams.warpSpeed))
  params.set(wire.gravitonicMovement, connectionsParams.gravitonicMovement ? 'true' : 'false')
  params.set(wire.flareMode, connectionsParams.flareMode)
  params.set(wire.flareDepth, String(connectionsParams.flareDepth))
  if (deriveIncludeIllustrativeRoutes(connectionsParams.flareMode, connectionsParams.flareDepth)) {
    params.set(wire.includeIllustrativeRoutes, 'true')
  }
}
