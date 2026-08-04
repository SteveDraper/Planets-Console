/**
 * Tabular candidate view for Homeworld locator -- read-only mirror of the sidebar panel.
 * Uses the same sector grouping when homeworld-sector overlays are present.
 */

import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { AnalyticShellScope } from '../../api/bff'
import { fetchAnalyticMap } from '../../api/bff'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { errorDetailFromUnknown } from '../../lib/queryRetry'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { useShellStore } from '../../stores/shell'
import { useHomeworldLocatorSelectionStore } from '../../stores/homeworldLocatorSelection'
import { useHomeworldRegionSelectionStore } from '../../stores/homeworldRegionSelection'
import { BASE_MAP_ANALYTIC_ID } from '../mapAnalyticIds'
import {
  HOMEWORLD_LOCATOR_ANALYTIC_ID,
  homeworldInactiveHint,
} from './constants'
import { fetchHomeworldLocatorTable } from './api'
import { HomeworldCandidateRows } from './HomeworldCandidateRows'
import { HomeworldSectorAccordion } from './HomeworldSectorAccordion'
import { buildHomeworldSectorPanelModel } from './homeworldSectorPanelModel'
import {
  fetchHomeworldLocatorMapDataResponse,
  homeworldLocatorMapQueryKey,
} from './mapAnalytic'
import { planetPositionsFromBaseMap } from './planetPositionsFromBaseMap'

const EMPTY_ROSTER: readonly PerspectiveRow[] = []
const EMPTY_OVERLAYS: readonly MapRegionOverlay[] = []
const EMPTY_POSITIONS: ReadonlyMap<number, { x: number; y: number }> = new Map()

type HomeworldLocatorTableTileProps = {
  analyticScope: AnalyticShellScope | null
  fetchEnabled: boolean
}

/**
 * Tabular candidate rows for Homeworld locator -- read-only mirror of the sidebar panel.
 */
export function HomeworldLocatorTableTile({
  analyticScope,
  fetchEnabled,
}: HomeworldLocatorTableTileProps) {
  const perspectives = useShellStore((s) => s.gameInfoContext?.perspectives)
  const roster = perspectives ?? EMPTY_ROSTER
  const selection = useHomeworldLocatorSelectionStore((s) => s.selection)
  const setSelection = useHomeworldLocatorSelectionStore((s) => s.setSelection)
  const selectedPlanetId = selection?.kind === 'planet' ? selection.planetId : null

  const selectedSectorIndexes = useHomeworldRegionSelectionStore(
    (s) => s.selectedSectorIndexes
  )
  const toggleSectorIndex = useHomeworldRegionSelectionStore((s) => s.toggleSectorIndex)
  const syncSelectionWithOverlays = useHomeworldRegionSelectionStore(
    (s) => s.syncSelectionWithOverlays
  )
  const selectedSectorIndexSet = useMemo(
    () => new Set(selectedSectorIndexes),
    [selectedSectorIndexes]
  )

  const tableQuery = useQuery({
    queryKey: ['analytic', HOMEWORLD_LOCATOR_ANALYTIC_ID, 'table', analyticScope] as const,
    queryFn: () => fetchHomeworldLocatorTable(analyticScope!),
    enabled: fetchEnabled && analyticScope != null,
  })
  const mapQuery = useQuery({
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

  useEffect(() => {
    if (!mapQuery.isSuccess || overlays.length === 0) return
    syncSelectionWithOverlays(overlays)
  }, [mapQuery.isSuccess, overlays, syncSelectionWithOverlays])

  const planetPositions = useMemo(() => {
    if (!baseMapQuery.isSuccess) return EMPTY_POSITIONS
    return planetPositionsFromBaseMap(baseMapQuery.data?.nodes ?? [])
  }, [baseMapQuery.isSuccess, baseMapQuery.data?.nodes])

  const panelModel = useMemo(() => {
    const rows = tableQuery.data?.rows ?? []
    if (!mapQuery.isSuccess) {
      return buildHomeworldSectorPanelModel(rows, EMPTY_OVERLAYS, EMPTY_POSITIONS)
    }
    return buildHomeworldSectorPanelModel(rows, overlays, planetPositions)
  }, [tableQuery.data?.rows, mapQuery.isSuccess, overlays, planetPositions])

  if (analyticScope == null) {
    return (
      <div className="p-4 text-sm text-gray-400">
        Load game info and choose a turn and viewpoint to load this analytic.
      </div>
    )
  }
  if (tableQuery.isPending) return <div className="p-4 text-sm text-gray-400">Loading…</div>
  if (tableQuery.error) {
    return (
      <div className="max-w-prose p-4 text-sm text-red-400 break-words">
        Error loading data. {errorDetailFromUnknown(tableQuery.error)}
      </div>
    )
  }
  const data = tableQuery.data
  if (data == null) return null

  if (!data.available) {
    return (
      <div className="p-4 text-sm text-slate-400">
        {homeworldInactiveHint(data.inactiveReason ?? null)}
      </div>
    )
  }

  const onSelectPlanet = (planetId: number) => setSelection({ kind: 'planet', planetId })

  if (panelModel.kind === 'sectors') {
    return (
      <HomeworldSectorAccordion
        mode="readOnly"
        sections={panelModel.sections}
        unassigned={panelModel.unassigned}
        baselineDegraded={data.baselineDegraded}
        baselineTurn={data.baselineTurn}
        roster={roster}
        selectedPlanetId={selectedPlanetId}
        onSelectPlanet={onSelectPlanet}
        selectedSectorIndexes={selectedSectorIndexSet}
        onToggleSectorIndex={toggleSectorIndex}
      />
    )
  }

  return (
    <HomeworldCandidateRows
      rows={panelModel.candidates}
      baselineDegraded={data.baselineDegraded}
      baselineTurn={data.baselineTurn}
      mode="readOnly"
      roster={roster}
      selectedPlanetId={selectedPlanetId}
      onSelectPlanet={onSelectPlanet}
    />
  )
}
