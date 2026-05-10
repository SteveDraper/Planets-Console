/** How flare-assisted routes are requested from Core (`flareMode` query). */
export type ConnectionsFlareMode = 'off' | 'include' | 'only'

/**
 * Max **hops** (1-3) for Core's mixed **normal-move + flare** reachability test.
 * Each hop is one normal well move or one flare, and a valid path must use at least one flare.
 */
export type ConnectionsFlareDepth = 1 | 2 | 3

/** Query parameters for the Connections map analytic (BFF forwards to Core). */
export type ConnectionsMapParams = {
  warpSpeed: number
  gravitonicMovement: boolean
  flareMode: ConnectionsFlareMode
  flareDepth: ConnectionsFlareDepth
}

export function appendConnectionsMapQueryParams(
  params: URLSearchParams,
  connectionsParams: ConnectionsMapParams
): void {
  params.set('warpSpeed', String(connectionsParams.warpSpeed))
  params.set('gravitonicMovement', connectionsParams.gravitonicMovement ? 'true' : 'false')
  params.set('flareMode', connectionsParams.flareMode)
  params.set('flareDepth', String(connectionsParams.flareDepth))
  // Illustrative routes (per-hop waypoints) are only useful when the hop budget can exceed one.
  if (connectionsParams.flareMode !== 'off' && connectionsParams.flareDepth >= 2) {
    params.set('includeIllustrativeRoutes', 'true')
  }
}
