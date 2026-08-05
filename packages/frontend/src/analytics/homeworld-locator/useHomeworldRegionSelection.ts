/**
 * Owns homeworld region-selection overlay reads and materialize writes.
 * Store stays dumb (preset + indexes); Tile / Panel / MapGraph share this hook.
 */

import { useCallback, useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { AnalyticShellScope } from '../../api/bff'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { useHomeworldRegionSelectionStore } from '../../stores/homeworldRegionSelection'
import {
  effectiveSelectedSectorIndexes,
  isHomeworldRegionSelectionUiPreset,
  materializeSectorIndexesForPreset,
  regionSelectionPresetForUi,
  sectorIndexListsEqual,
  toggleSectorIndexInSelection,
  type HomeworldRegionSelectionUiPreset,
} from './homeworldRegionSelection'
import {
  fetchHomeworldLocatorMapDataResponse,
  homeworldLocatorMapQueryKey,
} from './mapAnalytic'

const EMPTY_OVERLAYS: readonly MapRegionOverlay[] = []

export type UseHomeworldRegionSelectionOptions = {
  analyticScope: AnalyticShellScope | null
  /** When false, skip overlay fetch and materialize effects. */
  fetchEnabled: boolean
}

export function useHomeworldRegionSelection({
  analyticScope,
  fetchEnabled,
}: UseHomeworldRegionSelectionOptions) {
  const mapQuery = useQuery({
    queryKey: homeworldLocatorMapQueryKey(analyticScope),
    queryFn: () => fetchHomeworldLocatorMapDataResponse(analyticScope!),
    enabled: fetchEnabled && analyticScope != null,
  })
  const overlays = useMemo(
    () => mapQuery.data?.regionOverlays ?? EMPTY_OVERLAYS,
    [mapQuery.data?.regionOverlays]
  )

  const regionSelectionPreset = useHomeworldRegionSelectionStore(
    (s) => s.regionSelectionPreset
  )
  const storedSelectedSectorIndexes = useHomeworldRegionSelectionStore(
    (s) => s.selectedSectorIndexes
  )
  const showEnvelopeOverlays = useHomeworldRegionSelectionStore(
    (s) => s.showEnvelopeOverlays
  )
  const setRegionSelectionState = useHomeworldRegionSelectionStore(
    (s) => s.setRegionSelectionState
  )
  const setShowEnvelopeOverlays = useHomeworldRegionSelectionStore(
    (s) => s.setShowEnvelopeOverlays
  )

  const overlaysReady = fetchEnabled && mapQuery.isSuccess

  // Init-only ``all`` → Selected + explicit full list once overlays are known.
  useEffect(() => {
    if (!overlaysReady) return
    if (regionSelectionPreset !== 'all') return
    setRegionSelectionState(
      'selected',
      materializeSectorIndexesForPreset(overlays, 'all')
    )
  }, [
    overlaysReady,
    regionSelectionPreset,
    overlays,
    setRegionSelectionState,
  ])

  // Keep pinned/unpinned stored indexes aligned with overlay facts.
  useEffect(() => {
    if (!overlaysReady) return
    if (regionSelectionPreset !== 'pinned' && regionSelectionPreset !== 'unpinned') {
      return
    }
    const next = materializeSectorIndexesForPreset(overlays, regionSelectionPreset)
    if (sectorIndexListsEqual(storedSelectedSectorIndexes, next)) return
    setRegionSelectionState(regionSelectionPreset, next)
  }, [
    overlaysReady,
    regionSelectionPreset,
    overlays,
    storedSelectedSectorIndexes,
    setRegionSelectionState,
  ])

  const selectedSectorIndexes = useMemo(
    () =>
      effectiveSelectedSectorIndexes(
        overlays,
        regionSelectionPreset,
        storedSelectedSectorIndexes
      ),
    [overlays, regionSelectionPreset, storedSelectedSectorIndexes]
  )

  const selectedSectorIndexSet = useMemo(
    () => new Set(selectedSectorIndexes),
    [selectedSectorIndexes]
  )

  const uiPreset = regionSelectionPresetForUi(regionSelectionPreset)

  const setUiPreset = useCallback(
    (preset: HomeworldRegionSelectionUiPreset) => {
      if (!isHomeworldRegionSelectionUiPreset(preset)) return
      if (preset === 'selected') {
        const current = effectiveSelectedSectorIndexes(
          overlays,
          regionSelectionPreset,
          storedSelectedSectorIndexes
        )
        setRegionSelectionState('selected', current)
        return
      }
      setRegionSelectionState(
        preset,
        materializeSectorIndexesForPreset(overlays, preset)
      )
    },
    [
      overlays,
      regionSelectionPreset,
      storedSelectedSectorIndexes,
      setRegionSelectionState,
    ]
  )

  const toggleSectorIndex = useCallback(
    (sectorIndex: number) => {
      if (!Number.isInteger(sectorIndex) || sectorIndex < 0) return
      const current = effectiveSelectedSectorIndexes(
        overlays,
        regionSelectionPreset,
        storedSelectedSectorIndexes
      )
      setRegionSelectionState(
        'selected',
        toggleSectorIndexInSelection(current, sectorIndex)
      )
    },
    [
      overlays,
      regionSelectionPreset,
      storedSelectedSectorIndexes,
      setRegionSelectionState,
    ]
  )

  return {
    uiPreset,
    regionSelectionPreset,
    selectedSectorIndexes,
    selectedSectorIndexSet,
    showEnvelopeOverlays,
    setUiPreset,
    setShowEnvelopeOverlays,
    toggleSectorIndex,
    overlays,
    overlaysReady,
  }
}
