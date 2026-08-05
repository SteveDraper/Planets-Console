/**
 * Homeworld locator sidebar panel: sector accordion, refresh (#37 / #283).
 * Assert/revoke is map-context-menu only -- panel rows are read-only.
 */

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { AnalyticShellScope } from '../../api/bff'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { errorDetailFromUnknown } from '../../lib/queryRetry'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { fetchHomeworldLocatorTable } from './api'
import {
  HOMEWORLD_LOCATOR_ANALYTIC_ID,
  homeworldInactiveHint,
} from './constants'
import { HomeworldCandidateRows } from './HomeworldCandidateRows'
import { HomeworldSectorAccordion } from './HomeworldSectorAccordion'
import { buildHomeworldSectorPanelModel } from './homeworldSectorPanelModel'
import { useHomeworldLocatorRefreshMutation } from './useHomeworldLocatorMutations'
import type { HomeworldCandidateRecord } from './wireSchema'

export type HomeworldLocatorPanelProps = {
  analyticScope: AnalyticShellScope | null
  fetchEnabled: boolean
  roster: readonly PerspectiveRow[]
  selectedPlanetId: number | null
  onSelectPlanet: (planetId: number) => void
  /** Region selection from Tile (single selection-API owner under the sidebar). */
  selectedSectorIndexes: ReadonlySet<number>
  onToggleSectorIndex: (sectorIndex: number) => void
  /**
   * Sector overlays from Tile's ``useHomeworldLocatorMapOverlays`` (same
   * homeworld map-layer query as the map shell). Panel must not declare its
   * own homeworld map fetch.
   */
  overlays: readonly MapRegionOverlay[]
  /** True when Tile's homeworld map-layer query succeeded (not materialize readiness). */
  homeworldMapOverlaysQuerySucceeded: boolean
  /**
   * Planet positions from Tile's ``useBaseMapPlanetPositions`` (same base-map
   * query as the map shell). Panel must not declare its own base-map fetch.
   */
  planetPositions: ReadonlyMap<number, { x: number; y: number }>
  positionsReady: boolean
  positionsError: unknown | null
}

export function HomeworldLocatorPanel({
  analyticScope,
  fetchEnabled,
  roster,
  selectedPlanetId,
  onSelectPlanet,
  selectedSectorIndexes,
  onToggleSectorIndex,
  overlays,
  homeworldMapOverlaysQuerySucceeded,
  planetPositions,
  positionsReady,
  positionsError,
}: HomeworldLocatorPanelProps) {
  const tableQuery = useQuery({
    queryKey: ['analytic', HOMEWORLD_LOCATOR_ANALYTIC_ID, 'table', analyticScope] as const,
    queryFn: () => fetchHomeworldLocatorTable(analyticScope!),
    enabled: fetchEnabled && analyticScope != null,
  })
  // Hold until overlays are known -- building with empty overlays flashes a flat
  // list before the sector accordion appears on circular maps.
  const awaitingOverlays = !homeworldMapOverlaysQuerySucceeded
  // Sector grouping needs planet positions. Until they are ready, do not build
  // a sectors model (empty positions would dump every candidate into Unassigned).
  const needsBaseMap = homeworldMapOverlaysQuerySucceeded && overlays.length > 0
  const awaitingBaseMapForSectors = needsBaseMap && !positionsReady
  const awaitingSectorModel = awaitingOverlays || awaitingBaseMapForSectors

  const panelModel = useMemo(() => {
    if (awaitingSectorModel) return null
    const rows: readonly HomeworldCandidateRecord[] = tableQuery.data?.rows ?? []
    return buildHomeworldSectorPanelModel(rows, overlays, planetPositions)
  }, [
    tableQuery.data?.rows,
    awaitingSectorModel,
    overlays,
    planetPositions,
  ])

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
      {needsBaseMap && positionsError != null ? (
        <p className="text-[10px] text-red-400 break-words" role="alert">
          {errorDetailFromUnknown(positionsError)}
        </p>
      ) : null}
      {awaitingSectorModel ? (
        awaitingBaseMapForSectors && positionsError != null ? null : (
          <p className="px-0.5 text-[11px] text-slate-400">Loading…</p>
        )
      ) : panelModel?.kind === 'sectors' ? (
        <HomeworldSectorAccordion
          sections={panelModel.sections}
          unassigned={panelModel.unassigned}
          baselineDegraded={data.baselineDegraded}
          baselineTurn={data.baselineTurn}
          roster={roster}
          selectedPlanetId={selectedPlanetId}
          onSelectPlanet={onSelectPlanet}
          compact
          selectedSectorIndexes={selectedSectorIndexes}
          onToggleSectorIndex={onToggleSectorIndex}
        />
      ) : panelModel?.kind === 'flat' ? (
        <HomeworldCandidateRows
          rows={panelModel.candidates}
          baselineDegraded={data.baselineDegraded}
          baselineTurn={data.baselineTurn}
          roster={roster}
          selectedPlanetId={selectedPlanetId}
          onSelectPlanet={onSelectPlanet}
          compact
        />
      ) : null}
    </div>
  )
}
