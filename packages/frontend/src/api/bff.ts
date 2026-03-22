/**
 * BFF client — frontend talks only to BFF, never to Core API.
 */

const BFF_BASE = '' // proxy in dev: /bff -> backend

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

export type MapDataResponse = {
  analyticId: string
  nodes: MapNode[]
  edges: { source: string; target: string }[]
}

/**
 * Parses each node so `planet` / `ownerName` are plain objects (not lost to reference sharing).
 * Accepts `Planet` as an alternate key for the nested snapshot (defensive).
 */
export function normalizeMapDataResponse(raw: unknown): MapDataResponse {
  if (raw == null || typeof raw !== 'object') {
    return { analyticId: '', nodes: [], edges: [] }
  }
  const o = raw as Record<string, unknown>
  const nodesRaw = o.nodes
  const edgesRaw = o.edges
  const nodes = Array.isArray(nodesRaw) ? nodesRaw.map(normalizeMapNode) : []
  const edges = Array.isArray(edgesRaw)
    ? (edgesRaw as MapDataResponse['edges']).filter(
        (e) => e != null && typeof e === 'object' && 'source' in e && 'target' in e
      )
    : []
  return {
    analyticId: typeof o.analyticId === 'string' ? o.analyticId : String(o.analyticId ?? ''),
    nodes,
    edges,
  }
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

/** Combined nodes/edges from multiple analytics for the single shared map. */
export type CombinedMapData = {
  nodes: MapDataResponse['nodes']
  edges: MapDataResponse['edges']
}

export type StoredGameItem = {
  id: string
}

export type GamesListResponse = {
  games: StoredGameItem[]
}

export async function fetchGames(): Promise<GamesListResponse> {
  const endpointLabel = 'GET /bff/games'
  const r = await fetch(`${BFF_BASE}/bff/games`)
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

/** Ensures turn data exists in Core storage (Planets.nu loadturn when missing). */
export async function ensureTurnData(
  gameId: string,
  params: EnsureTurnParams
): Promise<{ ready: true }> {
  const trimmedUser = params.username.trim()
  if (!trimmedUser) {
    throw new Error('Set login name in the header before loading turn data.')
  }
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
  const r = await fetch(`${BFF_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
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
  const r = await fetch(`${BFF_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
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
  const endpointLabel = 'GET /bff/analytics'
  const r = await fetch(`${BFF_BASE}/bff/analytics`)
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

export async function fetchAnalyticTable(
  analyticId: string,
  scope: AnalyticShellScope
): Promise<TableDataResponse> {
  const path = `/bff/analytics/${encodeURIComponent(analyticId)}/table`
  const qs = analyticScopeQuery(scope)
  const endpointLabel = `GET ${path}`
  const r = await fetch(`${BFF_BASE}${path}${qs}`)
  if (!r.ok) {
    throw new Error(withEndpointIfGeneric(String(r.status), endpointLabel))
  }
  return r.json()
}

export async function fetchAnalyticMap(
  analyticId: string,
  scope: AnalyticShellScope
): Promise<MapDataResponse> {
  const path = `/bff/analytics/${encodeURIComponent(analyticId)}/map`
  const qs = analyticScopeQuery(scope)
  const endpointLabel = `GET ${path}`
  const r = await fetch(`${BFF_BASE}${path}${qs}`)
  if (!r.ok) {
    throw new Error(withEndpointIfGeneric(String(r.status), endpointLabel))
  }
  const raw = await r.json()
  return normalizeMapDataResponse(raw)
}
