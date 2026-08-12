/**
 * Homeworld locator sidebar panel: sector/player accordion, refresh (#37 / #283).
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
import {
  HomeworldPlayerAccordion,
  HomeworldSectorAccordion,
} from './HomeworldLocatorAccordion'
import { buildHomeworldLocatorPanelModel } from './homeworldLocatorPanelModel'
import { homeworldSectorsPresentOnMap } from './homeworldSectorIndex'
import { useHomeworldLocatorRefreshMutation } from './useHomeworldLocatorMutations'
import type { HomeworldCandidateRecord } from './wireSchema'

export type HomeworldLocatorPanelProps = {
  analyticScope: AnalyticShellScope | null
  fetchEnabled: boolean
  roster: readonly PerspectiveRow[]
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
  /** Settled failure from Tile's homeworld map-layer query (null while pending/success). */
  overlaysError: unknown | null
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
  onSelectPlanet,
  selectedSectorIndexes,
  onToggleSectorIndex,
  overlays,
  homeworldMapOverlaysQuerySucceeded,
  overlaysError,
  planetPositions,
  positionsReady,
  positionsError,
}: HomeworldLocatorPanelProps) {
  const tableQuery = useQuery({
    queryKey: ['analytic', HOMEWORLD_LOCATOR_ANALYTIC_ID, 'table', analyticScope] as const,
    queryFn: () => fetchHomeworldLocatorTable(analyticScope!),
    enabled: fetchEnabled && analyticScope != null,
  })
  // Hold until overlays are known -- building with empty overlays flashes player
  // tiles before the sector accordion appears on circular maps. Settled failure
  // is not "awaiting" (surface overlaysError instead of perpetual Loading).
  const awaitingOverlays =
    !homeworldMapOverlaysQuerySucceeded && overlaysError == null
  // Sector grouping needs planet positions. Planet-envelope / player mode does not.
  // Until positions are ready, do not build a sectors model (empty positions would
  // dump every candidate into Unassigned).
  const needsBaseMap =
    homeworldMapOverlaysQuerySucceeded && homeworldSectorsPresentOnMap(overlays)
  const awaitingBaseMapForSectors = needsBaseMap && !positionsReady
  const awaitingPanelModel = awaitingOverlays || awaitingBaseMapForSectors

  const panelModel = useMemo(() => {
    if (awaitingPanelModel) return null
    const rows: readonly HomeworldCandidateRecord[] = tableQuery.data?.rows ?? []
    return buildHomeworldLocatorPanelModel(rows, overlays, planetPositions, roster)
  }, [
    tableQuery.data?.rows,
    awaitingPanelModel,
    overlays,
    planetPositions,
    roster,
  ])

  const refreshMutation = useHomeworldLocatorRefreshMutation(analyticScope)

  if (analyticScope == null) {
    return (
      <p className="px-0.5 text-[11px] text-slate-400">
        Load game info and choose a turn and viewpoint to annotate homeworlds.
      </p>
    )
  }
  if (!fetchEnabled || tableQuery.isPending) {
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
      {overlaysError != null ? (
        <p className="text-[10px] text-red-400 break-words" role="alert">
          {errorDetailFromUnknown(overlaysError)}
        </p>
      ) : null}
      {needsBaseMap && positionsError != null ? (
        <p className="text-[10px] text-red-400 break-words" role="alert">
          {errorDetailFromUnknown(positionsError)}
        </p>
      ) : null}
      {awaitingPanelModel ? (
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
          onSelectPlanet={onSelectPlanet}
          compact
          selectedSectorIndexes={selectedSectorIndexes}
          onToggleSectorIndex={onToggleSectorIndex}
        />
      ) : panelModel?.kind === 'players' ? (
        <HomeworldPlayerAccordion
          sections={panelModel.sections}
          baselineDegraded={data.baselineDegraded}
          baselineTurn={data.baselineTurn}
          roster={roster}
          onSelectPlanet={onSelectPlanet}
          compact
        />
      ) : null}
    </div>
  )
}
