/**
 * BFF client — frontend talks only to BFF, never to Core API.
 */

const BFF_BASE = '' // proxy in dev: /bff -> backend

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
}

export type MapDataResponse = {
  analyticId: string
  nodes: MapNode[]
  edges: { source: string; target: string }[]
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
  const r = await fetch(`${BFF_BASE}/bff/games`)
  if (!r.ok) throw new Error(String(r.status))
  return r.json()
}

export async function fetchAnalytics(): Promise<AnalyticsListResponse> {
  const r = await fetch(`${BFF_BASE}/bff/analytics`)
  if (!r.ok) throw new Error(String(r.status))
  return r.json()
}

export async function fetchAnalyticTable(analyticId: string): Promise<TableDataResponse> {
  const r = await fetch(`${BFF_BASE}/bff/analytics/${encodeURIComponent(analyticId)}/table`)
  if (!r.ok) throw new Error(String(r.status))
  return r.json()
}

export async function fetchAnalyticMap(analyticId: string): Promise<MapDataResponse> {
  const r = await fetch(`${BFF_BASE}/bff/analytics/${encodeURIComponent(analyticId)}/map`)
  if (!r.ok) throw new Error(String(r.status))
  return r.json()
}
