/**
 * Homeworld locator sidebar panel: candidate table, assert/revoke, refresh (#37).
 */

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { AnalyticShellScope, MapNode } from '../../api/bff'
import { fetchAnalyticMap } from '../../api/bff'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { errorDetailFromUnknown } from '../../lib/queryRetry'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { BASE_MAP_ANALYTIC_ID } from '../mapAnalyticIds'
import { fetchHomeworldLocatorTable } from './api'
import { buildPlanetOwnershipTargets } from './buildPlanetOwnershipTargets'
import {
  HOMEWORLD_LOCATOR_ANALYTIC_ID,
  homeworldInactiveHint,
} from './constants'
import { HomeworldCandidateRows } from './HomeworldCandidateRows'
import {
  fetchHomeworldLocatorMapDataResponse,
  homeworldLocatorMapQueryKey,
} from './mapAnalytic'
import {
  useHomeworldLocatorAssertionMutation,
  useHomeworldLocatorRefreshMutation,
} from './useHomeworldLocatorMutations'
import type { OwnershipAssertTarget } from './resolveOwnershipAssertTarget'
import type { HomeworldCandidateRecord } from './wireSchema'

const EMPTY_OVERLAYS: readonly MapRegionOverlay[] = []

function planetIdFromBaseMapNode(node: MapNode): number | null {
  const raw = node.planet?.id
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    return Math.trunc(raw)
  }
  if (typeof raw === 'string' && raw.trim() !== '') {
    const parsed = Number.parseInt(raw.trim(), 10)
    if (Number.isFinite(parsed)) return parsed
  }
  const localId = node.id.includes(':') ? node.id.slice(node.id.indexOf(':') + 1) : node.id
  const match = /^p(\d+)$/.exec(localId)
  if (match != null) {
    return Number.parseInt(match[1]!, 10)
  }
  return null
}

function planetPositionsFromBaseMap(nodes: readonly MapNode[]): Map<number, { x: number; y: number }> {
  const out = new Map<number, { x: number; y: number }>()
  for (const node of nodes) {
    const planetId = planetIdFromBaseMapNode(node)
    if (planetId == null) continue
    out.set(planetId, { x: Number(node.x), y: Number(node.y) })
  }
  return out
}

export type HomeworldLocatorPanelProps = {
  analyticScope: AnalyticShellScope | null
  fetchEnabled: boolean
  roster: readonly PerspectiveRow[]
  selectedPlanetId: number | null
  onSelectPlanet: (planetId: number) => void
}

export function HomeworldLocatorPanel({
  analyticScope,
  fetchEnabled,
  roster,
  selectedPlanetId,
  onSelectPlanet,
}: HomeworldLocatorPanelProps) {
  const tableQuery = useQuery({
    queryKey: ['analytic', HOMEWORLD_LOCATOR_ANALYTIC_ID, 'table', analyticScope] as const,
    queryFn: () => fetchHomeworldLocatorTable(analyticScope!),
    enabled: fetchEnabled && analyticScope != null,
  })
  const mapQuery = useQuery({
    // Same key + MapDataResponse shape as ``homeworldLocatorMapAnalytic`` -- do not
    // return a partial payload here or markers disappear from the map layer cache.
    queryKey: homeworldLocatorMapQueryKey(analyticScope),
    queryFn: () => fetchHomeworldLocatorMapDataResponse(analyticScope!),
    enabled: fetchEnabled && analyticScope != null,
  })
  const overlays = useMemo(
    () => mapQuery.data?.regionOverlays ?? EMPTY_OVERLAYS,
    [mapQuery.data?.regionOverlays]
  )
  const needsBaseMap = overlays.length > 0
  const baseMapQuery = useQuery({
    queryKey: ['analytic', BASE_MAP_ANALYTIC_ID, 'map', analyticScope] as const,
    queryFn: () => fetchAnalyticMap(BASE_MAP_ANALYTIC_ID, analyticScope!),
    enabled: fetchEnabled && analyticScope != null && needsBaseMap,
  })

  const ownershipByPlanet = useMemo(() => {
    const positions = planetPositionsFromBaseMap(baseMapQuery.data?.nodes ?? [])
    // When no sector overlays, planet-keyed targets for every table row.
    if (overlays.length === 0) {
      const rows = tableQuery.data?.rows ?? []
      const map = new Map<number, OwnershipAssertTarget>()
      for (const row of rows) {
        map.set(row.planetId, { keying: 'planet', planetId: row.planetId })
      }
      return map
    }
    return buildPlanetOwnershipTargets(overlays, positions)
  }, [overlays, baseMapQuery.data?.nodes, tableQuery.data?.rows])

  const assertMutation = useHomeworldLocatorAssertionMutation(analyticScope)
  const refreshMutation = useHomeworldLocatorRefreshMutation(analyticScope)
  const mutationPending = assertMutation.isPending || refreshMutation.isPending

  if (analyticScope == null) {
    return (
      <p className="px-0.5 text-[11px] text-slate-400">
        Load game info and choose a turn and viewpoint to annotate homeworlds.
      </p>
    )
  }
  if (tableQuery.isPending) {
    return <p className="px-0.5 text-[11px] text-slate-400">Loading…</p>
  }
  if (tableQuery.error) {
    return (
      <p className="px-0.5 text-[11px] text-red-400 break-words">
        {errorDetailFromUnknown(tableQuery.error)}
      </p>
    )
  }
  const data = tableQuery.data
  if (data == null) return null
  if (!data.available) {
    return (
      <p className="px-0.5 text-[11px] text-slate-400">
        {homeworldInactiveHint(data.inactiveReason ?? null)}
      </p>
    )
  }

  const rows: readonly HomeworldCandidateRecord[] = data.rows ?? []
  const mutationError = assertMutation.error ?? refreshMutation.error

  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <div className="flex items-center justify-between gap-1">
        <span className="text-[10px] font-medium uppercase tracking-wide text-slate-400">
          Locator panel
        </span>
        <button
          type="button"
          className="rounded border border-[#52575d] px-1.5 py-0.5 text-[10px] text-slate-200 hover:bg-black/20 disabled:opacity-40"
          disabled={mutationPending}
          onClick={() => refreshMutation.mutate()}
        >
          {refreshMutation.isPending ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
      {mutationError != null ? (
        <p className="text-[10px] text-red-400 break-words" role="alert">
          {errorDetailFromUnknown(mutationError)}
        </p>
      ) : null}
      <HomeworldCandidateRows
        rows={rows}
        baselineDegraded={data.baselineDegraded}
        baselineTurn={data.baselineTurn}
        mode="interactive"
        compact
        roster={roster}
        selectedPlanetId={selectedPlanetId}
        onSelectPlanet={onSelectPlanet}
        mutationPending={mutationPending}
        resolveOwnershipTarget={(row) => ownershipByPlanet.get(row.planetId) ?? null}
        onAssertLocation={(planetId) =>
          assertMutation.mutate({
            axis: 'location',
            action: 'upsert',
            planetId,
          })
        }
        onRevokeLocation={(planetId) =>
          assertMutation.mutate({
            axis: 'location',
            action: 'revoke',
            planetId,
          })
        }
        onAssertOwnership={(target, ownerSlot) =>
          assertMutation.mutate({
            axis: 'ownership',
            action: 'upsert',
            ownerSlot,
            planetId: target.keying === 'planet' ? target.planetId : (target.planetId ?? null),
            sectorIndex: target.keying === 'sector' ? target.sectorIndex : null,
          })
        }
        onRevokeOwnership={(target, ownerSlot) =>
          assertMutation.mutate({
            axis: 'ownership',
            action: 'revoke',
            ownerSlot,
            planetId: target.keying === 'planet' ? target.planetId : (target.planetId ?? null),
            sectorIndex: target.keying === 'sector' ? target.sectorIndex : null,
          })
        }
      />
    </div>
  )
}
