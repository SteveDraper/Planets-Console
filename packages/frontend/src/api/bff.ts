/**
 * BFF client — frontend talks only to BFF, never to Core API.
 */

import { appendConnectionsMapQueryParams } from '../analytics/connections/api'
import type { ConnectionsMapParams } from '../analytics/connections/api'
import type {
  MapDataResponse,
  StellarCartographySampleResponse,
  StellarCartographyTurnSummaryResponse,
} from './bffCartographyTypes'
import { normalizeMapDataResponse } from './normalizeMapDataResponse'

const BFF_BASE = '' // proxy in dev: /bff -> backend

export type {
  ConnectionsFlareDepth,
  ConnectionsFlareMode,
  ConnectionsMapParams,
} from '../analytics/connections/api'

export type {
  BlackHoleOverlayCircle,
  CartographyOverlayLayerId,
  CombinedMapData,
  DebrisDiskOverlayCircle,
  IllustrativeRouteStep,
  IonStormOverlayCircle,
  MapCell,
  MapDataResponse,
  MapEdge,
  MapNode,
  MapPlanetSnapshot,
  NebulaOverlayCircle,
  NormalWellMapCell,
  PlanetPairRoute,
  RouteMapWaypoint,
  NeutronClusterOverlayCircle,
  StarClusterOverlayCircle,
  StellarCartographyOverlayCircle,
  StellarCartographySampleEntry,
  StellarCartographySampleLayerId,
  StellarCartographySampleResponse,
  StellarCartographyTurnSummaryResponse,
  WormholeUnknownEntrance,
} from './bffCartographyTypes'

export { isStellarCartographySampleLayerId } from './bffCartographyTypes'
export { normalizeMapDataResponse } from './normalizeMapDataResponse'
export type { BlackHoleConceptConstants } from '../lib/cartography/blackHoleOverlay'

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

/** True when a BFF fetch failed because the requested store path does not exist (HTTP 404). */
export function isBffNotFoundError(err: unknown): boolean {
  if (!(err instanceof Error)) {
    return false
  }
  const msg = err.message.trim()
  if (/^404\b/.test(msg)) {
    return true
  }
  if (msg.startsWith('Not Found')) {
    return true
  }
  return msg.startsWith('Document not found:') || msg.startsWith('Path does not exist:')
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

export type StoredTurnPerspectivesResponse = {
  perspectives: number[]
}

/** Perspective slots that already have turn data in storage (no Planets.nu). */
export async function fetchStoredTurnPerspectives(
  gameId: string,
  turn: number
): Promise<StoredTurnPerspectivesResponse> {
  const path = `/bff/games/${encodeURIComponent(gameId)}/turns/${encodeURIComponent(String(turn))}/stored-perspectives`
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
    appendConnectionsMapQueryParams(params, connectionsParams)
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

export async function fetchStellarCartographySample(
  scope: AnalyticShellScope,
  x: number,
  y: number
): Promise<StellarCartographySampleResponse> {
  const path = `/bff/games/${encodeURIComponent(scope.gameId)}/${scope.perspective}/turns/${scope.turn}/concepts/stellar-cartography/sample`
  const params = new URLSearchParams({ x: String(x), y: String(y) })
  const endpointLabel = `GET ${path}`
  const r = await bffRequest(`${path}?${params.toString()}`, { cache: 'no-store' }, endpointLabel)
  if (!r.ok) {
    throw new Error(withEndpointIfGeneric(String(r.status), endpointLabel))
  }
  return r.json()
}

export async function fetchStellarCartographyTurnSummary(
  scope: AnalyticShellScope
): Promise<StellarCartographyTurnSummaryResponse> {
  const path = `/bff/games/${encodeURIComponent(scope.gameId)}/${scope.perspective}/turns/${scope.turn}/concepts/stellar-cartography/summary`
  const endpointLabel = `GET ${path}`
  const r = await bffRequest(path, { cache: 'no-store' }, endpointLabel)
  if (!r.ok) {
    throw new Error(withEndpointIfGeneric(String(r.status), endpointLabel))
  }
  return r.json()
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

const DIAGNOSTICS_RECENT_404_HELP =
  'HTTP 404 for /bff/diagnostics/recent and /diagnostics/recent. ' +
  'Run `uv run serve` from the repo root so the process on :8000 includes the BFF (not the Core API alone). ' +
  'Confirm the Vite proxy in vite.config.ts forwards /bff and /diagnostics to that port.'

export async function fetchDiagnosticsRecent(): Promise<DiagnosticsRecentResponse> {
  const attempts: [string, string][] = [
    ['/bff/diagnostics/recent', 'GET /bff/diagnostics/recent'],
    [
      '/diagnostics/recent',
      'GET /diagnostics/recent (server alias; use if /bff is not proxied)',
    ],
  ]
  let lastNetworkError: Error | null = null
  let notFoundCount = 0
  for (const [path, label] of attempts) {
    let r: Response
    try {
      r = await bffRequest(path, undefined, label)
    } catch (e) {
      lastNetworkError = e instanceof Error ? e : new Error(String(e))
      continue
    }
    if (r.ok) {
      return (await r.json()) as DiagnosticsRecentResponse
    }
    if (r.status !== 404) {
      const body = await r.text().catch(() => '')
      const clip = body.length > 400 ? `${body.slice(0, 400)}…` : body
      // Do not use `withEndpointIfGeneric` here: a body snippet (e.g. "500: <html>…") is not
      // a "generic" message, so the label would be omitted. Always include the attempt label.
      const parts: string[] = [label, `HTTP ${r.status}`]
      if (clip) parts.push(clip)
      throw new Error(parts.join(' — '))
    }
    notFoundCount += 1
  }
  if (notFoundCount === attempts.length) {
    throw new Error(DIAGNOSTICS_RECENT_404_HELP)
  }
  if (lastNetworkError != null) {
    if (notFoundCount > 0) {
      throw new Error(
        'Diagnostics: one path could not be reached, another returned HTTP 404. ' +
          `Tried: ${attempts.map((a) => a[0]).join(' → ')}. ` +
          `Last connection error: ${lastNetworkError.message}`
      )
    }
    throw new Error(
      `Diagnostics: could not reach any diagnostics recent path (${attempts.map((a) => a[0]).join(' → ')}). ` +
        `Last error: ${lastNetworkError.message}`
    )
  }
  throw new Error('Unexpected state in fetchDiagnosticsRecent')
}
