/**
 * Homeworld locator sidebar panel: sector accordion, refresh (#37 / #283).
 * Assert/revoke is map-context-menu only -- panel rows are read-only.
 */

import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { AnalyticShellScope } from '../../api/bff'
import { fetchAnalyticMap } from '../../api/bff'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { errorDetailFromUnknown } from '../../lib/queryRetry'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { useHomeworldRegionSelectionStore } from '../../stores/homeworldRegionSelection'
import { BASE_MAP_ANALYTIC_ID } from '../mapAnalyticIds'
import { fetchHomeworldLocatorTable } from './api'
import {
  HOMEWORLD_LOCATOR_ANALYTIC_ID,
  homeworldInactiveHint,
} from './constants'
import { HomeworldCandidateRows } from './HomeworldCandidateRows'
import { HomeworldSectorAccordion } from './HomeworldSectorAccordion'
import { buildHomeworldSectorPanelModel } from './homeworldSectorPanelModel'
import { useHomeworldLocatorRefreshMutation } from './useHomeworldLocatorMutations'
import { planetPositionsFromBaseMap } from './planetPositionsFromBaseMap'
import {
  fetchHomeworldLocatorMapDataResponse,
  homeworldLocatorMapQueryKey,
} from './mapAnalytic'
import type { HomeworldCandidateRecord } from './wireSchema'

const EMPTY_OVERLAYS: readonly MapRegionOverlay[] = []
const EMPTY_POSITIONS: ReadonlyMap<number, { x: number; y: number }> = new Map()

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

  const selectedSectorIndexes = useHomeworldRegionSelectionStore(
    (s) => s.selectedSectorIndexes
  )
  const toggleSectorIndex = useHomeworldRegionSelectionStore((s) => s.toggleSectorIndex)
  const syncSelectionWithOverlays = useHomeworldRegionSelectionStore(
    (s) => s.syncSelectionWithOverlays
  )

  useEffect(() => {
    if (!mapQuery.isSuccess || overlays.length === 0) return
    syncSelectionWithOverlays(overlays)
  }, [mapQuery.isSuccess, overlays, syncSelectionWithOverlays])

  const selectedSectorIndexSet = useMemo(
    () => new Set(selectedSectorIndexes),
    [selectedSectorIndexes]
  )

  const planetPositions = useMemo(() => {
    if (!baseMapQuery.isSuccess) return EMPTY_POSITIONS
    return planetPositionsFromBaseMap(baseMapQuery.data?.nodes ?? [])
  }, [baseMapQuery.isSuccess, baseMapQuery.data?.nodes])

  const panelModel = useMemo(() => {
    const rows: readonly HomeworldCandidateRecord[] = tableQuery.data?.rows ?? []
    if (!mapQuery.isSuccess) {
      return buildHomeworldSectorPanelModel(rows, EMPTY_OVERLAYS, EMPTY_POSITIONS)
    }
    return buildHomeworldSectorPanelModel(rows, overlays, planetPositions)
  }, [tableQuery.data?.rows, mapQuery.isSuccess, overlays, planetPositions])

  const refreshMutation = useHomeworldLocatorRefreshMutation(analyticScope)

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

  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <div className="flex items-center justify-between gap-1">
        <span className="text-[10px] font-medium uppercase tracking-wide text-slate-400">
          Locator panel
        </span>
        <button
          type="button"
          className="rounded border border-[#52575d] px-1.5 py-0.5 text-[10px] text-slate-200 hover:bg-black/20 disabled:opacity-40"
          disabled={refreshMutation.isPending}
          onClick={() => refreshMutation.mutate()}
        >
          {refreshMutation.isPending ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
      {refreshMutation.error != null ? (
        <p className="text-[10px] text-red-400 break-words" role="alert">
          {errorDetailFromUnknown(refreshMutation.error)}
        </p>
      ) : null}
      {needsBaseMap && baseMapQuery.error != null ? (
        <p className="text-[10px] text-red-400 break-words" role="alert">
          {errorDetailFromUnknown(baseMapQuery.error)}
        </p>
      ) : null}
      {panelModel.kind === 'sectors' ? (
        <HomeworldSectorAccordion
          sections={panelModel.sections}
          unassigned={panelModel.unassigned}
          baselineDegraded={data.baselineDegraded}
          baselineTurn={data.baselineTurn}
          roster={roster}
          selectedPlanetId={selectedPlanetId}
          onSelectPlanet={onSelectPlanet}
          compact
          selectedSectorIndexes={selectedSectorIndexSet}
          onToggleSectorIndex={toggleSectorIndex}
        />
      ) : (
        <HomeworldCandidateRows
          rows={panelModel.candidates}
          baselineDegraded={data.baselineDegraded}
          baselineTurn={data.baselineTurn}
          roster={roster}
          selectedPlanetId={selectedPlanetId}
          onSelectPlanet={onSelectPlanet}
          compact
        />
      )}
    </div>
  )
}
