/**
 * BFF client — frontend talks only to BFF, never to Core API.
 */

const BFF_BASE = '' // proxy in dev: /bff -> backend

/** When set in `sessionStorage`, all `/bff/...` requests get `?includeDiagnostics=true` (or `&...`). */
export const INCLUDE_DIAGNOSTICS_SESSION_KEY = 'planetsConsole.includeDiagnostics' as const

export function isIncludeDiagnosticsSessionEnabled(): boolean {
  if (typeof sessionStorage === 'undefined') {
    return false
  }
  return sessionStorage.getItem(INCLUDE_DIAGNOSTICS_SESSION_KEY) === '1'
}

export function setIncludeDiagnosticsSessionEnabled(enabled: boolean): void {
  if (typeof sessionStorage === 'undefined') {
    return
  }
  if (enabled) {
    sessionStorage.setItem(INCLUDE_DIAGNOSTICS_SESSION_KEY, '1')
  } else {
    sessionStorage.removeItem(INCLUDE_DIAGNOSTICS_SESSION_KEY)
  }
}

function appendIncludeDiagnosticsQuery(path: string): string {
  if (!path.startsWith('/bff/')) {
    return path
  }
  if (!isIncludeDiagnosticsSessionEnabled()) {
    return path
  }
  if (/[?&]includeDiagnostics=/.test(path)) {
    return path
  }
  const sep = path.includes('?') ? '&' : '?'
  return `${path}${sep}includeDiagnostics=true`
}

/**
 * When `fetch` rejects (no HTTP response), browsers often set only a generic
 * "Failed to fetch" / "Load failed" message. This keeps the original text but
 * adds method+path, the request URL path, and `cause` when present.
 */
export function toFetchRejectionError(
  err: unknown,
  endpointLabel: string,
  attemptedPath: string
): Error {
  const name = err instanceof Error ? err.name : 'Error'
  const message = err instanceof Error ? err.message : String(err)
  let cause = ''
  if (err instanceof Error && 'cause' in err) {
    const c = (err as Error & { cause?: unknown }).cause
    if (c != null) {
      cause = `; cause: ${String(c)}`
    }
  }
  return new Error(
    `${name}: ${message} — ${endpointLabel} (request: ${attemptedPath}). ` +
      `No HTTP response${cause}. ` +
      `Check BFF is running, the dev proxy targets it, and there is no CORS or connection problem.`
  )
}

async function bffRequest(
  path: string,
  init: RequestInit | undefined,
  endpointLabel: string
): Promise<Response> {
  const requestPath = appendIncludeDiagnosticsQuery(path)
  const url = `${BFF_BASE}${requestPath}`
  try {
    return await fetch(url, init)
  } catch (e) {
    throw toFetchRejectionError(e, endpointLabel, requestPath)
  }
}

/** Human-readable endpoint for error rows (method + path, no host). */
export function withEndpointIfGeneric(message: string, endpointLabel: string): string {
  const detail = message.trim()
  if (!isGenericServerErrorMessage(detail)) {
    return detail || 'Request failed'
  }
  if (detail.includes(endpointLabel)) {
    return detail || 'Request failed'
  }
  const base = detail || 'Request failed'
  return `${base} (${endpointLabel})`
}

export function isGenericServerErrorMessage(message: string): boolean {
  const t = message.trim().toLowerCase()
  if (t === '') {
    return true
  }
  if (t === 'internal server error') {
    return true
  }
  if (t === 'bad gateway') {
    return true
  }
  if (t === 'service unavailable') {
    return true
  }
  if (t === 'gateway timeout') {
    return true
  }
  // Response body or fallback was only an HTTP status code for a server error
  if (/^5\d\d$/.test(t)) {
    return true
  }
  return false
}

/** base = always-on map (planets + edges), not shown in pane. selectable = user can toggle. */
export type AnalyticType = 'base' | 'selectable'

export type AnalyticItem = {
  id: string
  name: string
  supportsTable: boolean
  supportsMap: boolean
  type?: AnalyticType
}

export type AnalyticsListResponse = {
  analytics: AnalyticItem[]
}

export type TableDataResponse = {
  analyticId: string
  columns: string[]
  rows: string[][]
}

/** Node position in the map's fixed Cartesian coordinate system. */
export type MapNode = {
  id: string
  label: string
  x: number
  y: number
  /** Present for base-map planets; full turn snapshot fields for map labels. */
  planet?: Record<string, unknown>
  /** Resolved from turn players when `planet` is present. */
  ownerName?: string | null
}

/** Edge in map wire format or after combining route pairs onto base-map node ids. */
export type MapEdge = {
  source: string
  target: string
  /** True when reachability uses a flare (dashed edge on the map). */
  viaFlare?: boolean
  /**
   * Intermediate map cells (game integer coordinates) between source and target.
   * When set, the map draws a polyline A → waypoints → B instead of a single segment.
   */
  waypointsInGame?: { x: number; y: number }[]
}

/** One hop in a Core `illustrativeRoute` (normal move or flare). */
export type IllustrativeRouteStep = {
  kind: 'normal' | 'flare'
  to: { x: number; y: number }
  waypointOffset?: [number, number]
  arrivalOffset?: [number, number]
}

/** UI-independent planet pair from the Connections analytic (Core/BFF). */
export type PlanetPairRoute = {
  fromPlanetId: number
  toPlanetId: number
  viaFlare: boolean
  /** Present when the server was asked for illustrative paths (multi-hop flares). */
  illustrativeRoute?: IllustrativeRouteStep[]
}

export type MapDataResponse = {
  analyticId: string
  nodes: MapNode[]
  edges: MapEdge[]
  routes?: PlanetPairRoute[]
}

/** How flare-assisted routes are requested from Core (`flareMode` query). */
export type ConnectionsFlareMode = 'off' | 'include' | 'only'

/**
 * Max **hops** (1–3) for Core’s mixed **normal-move + flare** reachability test: each hop is one
 * normal well move (within max travel) or one flare from the table, and a valid path must use
 * **at least one** flare. This is a hop **budget**, not a cap on “flares in a row.”
 * Pair **discovery** unions center-distance **annuli** for k = 1…N, so a higher value adds
 * candidate pairs and longer mixed paths; it does not drop links accepted at a smaller value.
 * Only used when `flareMode` is not `off` (no flare geometry otherwise).
 */
export type ConnectionsFlareDepth = 1 | 2 | 3

/** Query parameters for the Connections map analytic (BFF forwards to Core). */
export type ConnectionsMapParams = {
  warpSpeed: number
  gravitonicMovement: boolean
  flareMode: ConnectionsFlareMode
  /**
   * `flareDepth` query (1–3): hop budget for mixed normal+flare paths; at least one hop must be
   * a flare. Raising it widens per-k annulus search and can admit longer mixed paths.
   */
  flareDepth: ConnectionsFlareDepth
}

function parseFiniteNumberPair(
  s: Record<string, unknown>,
  camelKey: string,
  snakeKey: string
): [number, number] | undefined {
  const raw = s[camelKey] ?? s[snakeKey]
  if (raw == null) return undefined
  if (!Array.isArray(raw) || raw.length !== 2) return undefined
  const a = typeof raw[0] === 'number' ? raw[0] : Number(raw[0])
  const b = typeof raw[1] === 'number' ? raw[1] : Number(raw[1])
  if (!Number.isFinite(a) || !Number.isFinite(b)) return undefined
  return [a, b]
}

function normalizeIllustrativeRouteStep(raw: unknown): IllustrativeRouteStep | null {
  if (raw == null || typeof raw !== 'object') return null
  const s = raw as Record<string, unknown>
  const kind = s.kind === 'flare' ? 'flare' : s.kind === 'normal' ? 'normal' : null
  if (kind == null) return null
  const toRaw = s.to
  if (toRaw == null || typeof toRaw !== 'object') return null
  const t = toRaw as Record<string, unknown>
  const x = typeof t.x === 'number' ? t.x : Number(t.x)
  const y = typeof t.y === 'number' ? t.y : Number(t.y)
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null
  const out: IllustrativeRouteStep = { kind, to: { x, y } }
  const wp = parseFiniteNumberPair(s, 'waypointOffset', 'waypoint_offset')
  if (wp != null) {
    out.waypointOffset = wp
  }
  const ar = parseFiniteNumberPair(s, 'arrivalOffset', 'arrival_offset')
  if (ar != null) {
    out.arrivalOffset = ar
  }
  return out
}

/**
 * Parses each node so `planet` / `ownerName` are plain objects (not lost to reference sharing).
 * Accepts `Planet` as an alternate key for the nested snapshot (defensive).
 */
function normalizePlanetPairRoute(raw: unknown): PlanetPairRoute | null {
  if (raw == null || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  const fromRaw = r.fromPlanetId ?? r.from_planet_id
  const toRaw = r.toPlanetId ?? r.to_planet_id
  const fromPlanetId = typeof fromRaw === 'number' ? fromRaw : Number(fromRaw)
  const toPlanetId = typeof toRaw === 'number' ? toRaw : Number(toRaw)
  if (!Number.isFinite(fromPlanetId) || !Number.isFinite(toPlanetId)) return null
  let illustrativeRoute: IllustrativeRouteStep[] | undefined
  const irRaw = r.illustrativeRoute ?? r.illustrative_route
  if (Array.isArray(irRaw) && irRaw.length > 0) {
    const steps = irRaw
      .map(normalizeIllustrativeRouteStep)
      .filter((s): s is IllustrativeRouteStep => s != null)
    if (steps.length > 0) illustrativeRoute = steps
  }
  const o: PlanetPairRoute = {
    fromPlanetId,
    toPlanetId,
    viaFlare: r.viaFlare === true,
  }
  if (illustrativeRoute != null) {
    o.illustrativeRoute = illustrativeRoute
  }
  return o
}

function normalizeMapEdge(raw: unknown): MapEdge | null {
  if (raw == null || typeof raw !== 'object') return null
  const e = raw as Record<string, unknown>
  const source = typeof e.source === 'string' ? e.source : String(e.source ?? '')
  const target = typeof e.target === 'string' ? e.target : String(e.target ?? '')
  if (source === '' || target === '') return null
  const edge: MapEdge = { source, target }
  if (e.viaFlare === true) edge.viaFlare = true
  return edge
}

export function normalizeMapDataResponse(raw: unknown): MapDataResponse {
  if (raw == null || typeof raw !== 'object') {
    return { analyticId: '', nodes: [], edges: [] }
  }
  const o = raw as Record<string, unknown>
  const nodesRaw = o.nodes
  const edgesRaw = o.edges
  const routesRaw = o.routes
  const nodes = Array.isArray(nodesRaw) ? nodesRaw.map(normalizeMapNode) : []
  const edges = Array.isArray(edgesRaw)
    ? (edgesRaw.map(normalizeMapEdge).filter((e) => e != null) as MapEdge[])
    : []
  const routes = Array.isArray(routesRaw)
    ? (routesRaw.map(normalizePlanetPairRoute).filter((r) => r != null) as PlanetPairRoute[])
    : undefined
  const out: MapDataResponse = {
    analyticId: typeof o.analyticId === 'string' ? o.analyticId : String(o.analyticId ?? ''),
    nodes,
    edges,
  }
  if (routes != null) {
    out.routes = routes
  }
  return out
}

function normalizeMapNode(raw: unknown): MapNode {
  if (raw == null || typeof raw !== 'object') {
    return { id: '', label: '', x: 0, y: 0 }
  }
  const n = raw as Record<string, unknown>
  const nested = n.planet ?? n.Planet
  const planet =
    nested != null && typeof nested === 'object' && !Array.isArray(nested)
      ? ({ ...(nested as Record<string, unknown>) } as Record<string, unknown>)
      : undefined
  const base: MapNode = {
    id: typeof n.id === 'string' ? n.id : String(n.id ?? ''),
    label: typeof n.label === 'string' ? n.label : String(n.label ?? ''),
    x: typeof n.x === 'number' ? n.x : Number(n.x) || 0,
    y: typeof n.y === 'number' ? n.y : Number(n.y) || 0,
  }
  if (planet != null) {
    base.planet = planet
  }
  if (Object.prototype.hasOwnProperty.call(n, 'ownerName')) {
    base.ownerName = n.ownerName as string | null | undefined
  }
  return base
}

/** Intermediate cell along a multi-hop flare (game map integer coordinates), for subtle markers. */
export type RouteMapWaypoint = {
  id: string
  gx: number
  gy: number
}

/** Combined nodes/edges from multiple analytics for the single shared map. */
export type CombinedMapData = {
  nodes: MapDataResponse['nodes']
  edges: MapEdge[]
  /** Deduped intermediate cells for illustrated flare routes (when `includeIllustrativeRoutes` was requested). */
  routeWaypoints: RouteMapWaypoint[]
}

export type StoredGameItem = {
  id: string
  /** Cached game / settings title when `games/{id}/info` exists in storage. */
  sectorName?: string
}

export type GamesListResponse = {
  games: StoredGameItem[]
}

export async function fetchGames(): Promise<GamesListResponse> {
  const path = '/bff/games'
  const endpointLabel = 'GET /bff/games'
  const r = await bffRequest(path, undefined, endpointLabel)
  if (!r.ok) {
    throw new Error(withEndpointIfGeneric(String(r.status), endpointLabel))
  }
  return r.json()
}

export type RefreshGameInfoParams = {
  username: string
  password?: string
}

/** Core/BFF game info shape (subset); full payload matches Planets loadinfo. */
export type GameInfoResponse = {
  game: { id: number; name?: string; turn?: number; [key: string]: unknown }
  players?: unknown[]
  settings?: { turn?: number; [key: string]: unknown }
  [key: string]: unknown
}

export type EnsureTurnParams = {
  turn: number
  perspective: number
  username: string
  password?: string
}

export type ShellBootstrapResponse = {
  showInitialGame: string | null
}

export async function fetchShellBootstrap(): Promise<ShellBootstrapResponse> {
  const path = '/bff/shell/bootstrap'
  const endpointLabel = 'GET /bff/shell/bootstrap'
  const r = await bffRequest(path, undefined, endpointLabel)
  if (!r.ok) {
    throw new Error(withEndpointIfGeneric(String(r.status), endpointLabel))
  }
  return r.json()
}

/** Game info from server storage only (no Planets.nu refresh). */
export async function fetchStoredGameInfo(gameId: string): Promise<GameInfoResponse> {
  const path = `/bff/games/${encodeURIComponent(gameId)}/info`
  const endpointLabel = `GET ${path}`
  const r = await bffRequest(path, undefined, endpointLabel)
  if (!r.ok) {
    let detail = r.statusText
    try {
      const j: { detail?: string | unknown } = await r.json()
      if (j?.detail != null) {
        detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
      }
    } catch {
      /* use statusText */
    }
    throw new Error(withEndpointIfGeneric(detail, endpointLabel))
  }
  return r.json()
}

/**
 * Ensures turn data exists in Core storage (Planets.nu loadturn when missing).
 * Username may be empty when the turn is already stored (no upstream fetch).
 */
export async function ensureTurnData(
  gameId: string,
  params: EnsureTurnParams
): Promise<{ ready: true }> {
  const trimmedUser = params.username.trim()
  const body: {
    turn: number
    perspective: number
    username: string
    password?: string
  } = {
    turn: params.turn,
    perspective: params.perspective,
    username: trimmedUser,
  }
  if (params.password) {
    body.password = params.password
  }
  const path = `/bff/games/${encodeURIComponent(gameId)}/turns/ensure`
  const endpointLabel = `POST ${path}`
  const r = await bffRequest(
    path,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
    endpointLabel
  )
  if (!r.ok) {
    let detail = r.statusText
    try {
      const j: { detail?: string | unknown } = await r.json()
      if (j?.detail != null) {
        detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
      }
    } catch {
      /* use statusText */
    }
    throw new Error(withEndpointIfGeneric(detail, endpointLabel))
  }
  await r.json().catch(() => undefined)
  return { ready: true }
}

export async function refreshGameInfo(
  gameId: string,
  params: RefreshGameInfoParams
): Promise<GameInfoResponse> {
  const trimmedUser = params.username.trim()
  if (!trimmedUser) {
    throw new Error('Set login name in the header before selecting a game.')
  }
  const body: {
    operation: 'refresh'
    params: { username: string; password?: string }
  } = {
    operation: 'refresh',
    params: { username: trimmedUser },
  }
  if (params.password) {
    body.params.password = params.password
  }
  const path = `/bff/games/${encodeURIComponent(gameId)}/info`
  const endpointLabel = `POST ${path}`
  const r = await bffRequest(
    path,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
    endpointLabel
  )
  if (!r.ok) {
    let detail = r.statusText
    try {
      const j: { detail?: string | unknown } = await r.json()
      if (j?.detail != null) {
        detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
      }
    } catch {
      /* use statusText */
    }
    throw new Error(withEndpointIfGeneric(detail, endpointLabel))
  }
  return r.json()
}

export async function fetchAnalytics(): Promise<AnalyticsListResponse> {
  const path = '/bff/analytics'
  const endpointLabel = 'GET /bff/analytics'
  const r = await bffRequest(path, undefined, endpointLabel)
  if (!r.ok) {
    throw new Error(withEndpointIfGeneric(String(r.status), endpointLabel))
  }
  return r.json()
}

/** Scope for per-turn analytics (Core game id, turn, perspective slot). */
export type AnalyticShellScope = {
  gameId: string
  turn: number
  perspective: number
}

function analyticScopeQuery(scope: AnalyticShellScope): string {
  const params = new URLSearchParams({
    gameId: scope.gameId,
    turn: String(scope.turn),
    perspective: String(scope.perspective),
  })
  return `?${params.toString()}`
}

function analyticMapQueryString(
  scope: AnalyticShellScope,
  analyticId: string,
  connectionsParams: ConnectionsMapParams | undefined
): string {
  const params = new URLSearchParams({
    gameId: scope.gameId,
    turn: String(scope.turn),
    perspective: String(scope.perspective),
  })
  if (analyticId === 'connections' && connectionsParams != null) {
    params.set('warpSpeed', String(connectionsParams.warpSpeed))
    params.set(
      'gravitonicMovement',
      connectionsParams.gravitonicMovement ? 'true' : 'false'
    )
    params.set('flareMode', connectionsParams.flareMode)
    params.set('flareDepth', String(connectionsParams.flareDepth))
    // Illustrative routes (per-hop waypoints) are only useful when the hop budget can exceed one.
    if (connectionsParams.flareMode !== 'off' && connectionsParams.flareDepth >= 2) {
      params.set('includeIllustrativeRoutes', 'true')
    }
  }
  return `?${params.toString()}`
}

export async function fetchAnalyticTable(
  analyticId: string,
  scope: AnalyticShellScope
): Promise<TableDataResponse> {
  const path = `/bff/analytics/${encodeURIComponent(analyticId)}/table`
  const qs = analyticScopeQuery(scope)
  const endpointLabel = `GET ${path}`
  const r = await bffRequest(`${path}${qs}`, undefined, endpointLabel)
  if (!r.ok) {
    throw new Error(withEndpointIfGeneric(String(r.status), endpointLabel))
  }
  return r.json()
}

export async function fetchAnalyticMap(
  analyticId: string,
  scope: AnalyticShellScope,
  connectionsParams?: ConnectionsMapParams
): Promise<MapDataResponse> {
  const path = `/bff/analytics/${encodeURIComponent(analyticId)}/map`
  const qs = analyticMapQueryString(scope, analyticId, connectionsParams)
  const endpointLabel = `GET ${path}`
  const r = await bffRequest(`${path}${qs}`, { cache: 'no-store' }, endpointLabel)
  if (!r.ok) {
    throw new Error(withEndpointIfGeneric(String(r.status), endpointLabel))
  }
  const raw = await r.json()
  return normalizeMapDataResponse(raw)
}

// --- Server diagnostics (MRU buffer of request trees) ---

/**
 * Finitely nested JSON shape (natively JSON-serializable; matches Core/BFF `JSONValue` on trees).
 * Request roots usually attach only scalars; child nodes may add arrays or small objects.
 */
export type JsonValue =
  | null
  | string
  | number
  | boolean
  | JsonValue[]
  | { [key: string]: JsonValue }

export type DiagnosticTree = {
  name: string
  values: Record<string, JsonValue>
  timings: Record<string, number>
  children: DiagnosticTree[]
}

export type DiagnosticsRecentItem = {
  capturedAt: string
  summary: string
  diagnostics: DiagnosticTree
}

export type DiagnosticsRecentResponse = {
  items: DiagnosticsRecentItem[]
}

export async function fetchDiagnosticsRecent(): Promise<DiagnosticsRecentResponse> {
  const attempts: [string, string][] = [
    ['/bff/diagnostics/recent', 'GET /bff/diagnostics/recent'],
    [
      '/diagnostics/recent',
      'GET /diagnostics/recent (server alias; use if /bff is not proxied)',
    ],
  ]
  for (const [path, label] of attempts) {
    const r = await bffRequest(path, undefined, label)
    if (r.ok) {
      return (await r.json()) as DiagnosticsRecentResponse
    }
    if (r.status !== 404) {
      const body = await r.text().catch(() => '')
      const clip = body.length > 400 ? `${body.slice(0, 400)}…` : body
      throw new Error(
        withEndpointIfGeneric(
          clip ? `${r.status}: ${clip}` : String(r.status),
          label
        )
      )
    }
  }
  throw new Error(
    'HTTP 404 for /bff/diagnostics/recent and /diagnostics/recent. ' +
      'Run `uv run serve` from the repo root so the process on :8000 includes the BFF (not the Core API alone). ' +
      'Confirm the Vite proxy in vite.config.ts forwards /bff and /diagnostics to that port.'
  )
}
