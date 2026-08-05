/**
 * Owns homeworld region-selection writes and effective-index derivation for
 * Tile/Panel. Overlay bytes come from ``useHomeworldLocatorMapOverlays``
 * (same map-layer query as MapGraph registration) -- this hook does not fetch.
 *
 * Materialize effects (``all`` → selected) are owned solely by
 * ``useHomeworldRegionSelectionMaterialize`` -- call that once from MapGraph, fed from
 * homeworld sectors already present on combined ``data.regionOverlays``.
 *
 * Effective outline indexes (store preset + overlays → concrete list) are owned by
 * ``useEffectiveHomeworldSectorIndexes`` -- MapGraph and this hook both use it.
 *
 * Pinned/unpinned outline sets are derived at read time; do not continuously
 * rewrite stored indexes while those presets are active.
 */

import { useCallback, useEffect, useMemo } from 'react'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { useHomeworldRegionSelectionStore } from '../../stores/homeworldRegionSelectionStore'
import {
  effectiveSelectedSectorIndexes,
  isHomeworldRegionSelectionUiPreset,
  materializeSectorIndexesForPreset,
  regionSelectionPresetForUi,
  toggleSectorIndexInSelection,
  type HomeworldRegionSelectionUiPreset,
} from '../../lib/homeworldRegionSelection'

export type UseHomeworldRegionSelectionOptions = {
  /** Sector overlays from ``useHomeworldLocatorMapOverlays`` (shared map-layer cache). */
  overlays: readonly MapRegionOverlay[]
}

/**
 * Sole owner of store → effective sector-index derivation for a given overlays
 * array. MapGraph (combined homeworld sectors) and the sidebar selection hook
 * both use this -- no parallel useMemo wiring.
 */
export function useEffectiveHomeworldSectorIndexes(
  overlays: readonly MapRegionOverlay[]
): {
  selectedSectorIndexes: number[]
  selectedSectorIndexSet: ReadonlySet<number>
} {
  const regionSelectionPreset = useHomeworldRegionSelectionStore(
    (s) => s.regionSelectionPreset
  )
  const storedSelectedSectorIndexes = useHomeworldRegionSelectionStore(
    (s) => s.selectedSectorIndexes
  )

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

  return { selectedSectorIndexes, selectedSectorIndexSet }
}

/**
 * Sole owner of region-selection materialize writes. Mount once from MapGraph
 * with homeworld sectors from combined map ``regionOverlays`` (not a second
 * selection-hook fetch).
 *
 * Only init-only ``all`` → Selected + explicit full list once overlays are known.
 * Pinned/unpinned stay derive-at-read (no continuous store sync).
 */
export function useHomeworldRegionSelectionMaterialize(
  overlays: readonly MapRegionOverlay[],
  overlaysReady: boolean
): void {
  // Subscribe so the effect re-runs when preset leaves ``all`` (e.g. user toggle).
  // Read preset from getState() inside the effect so a same-frame toggle that
  // already wrote ``selected`` is not clobbered by a stale ``all`` closure.
  const regionSelectionPreset = useHomeworldRegionSelectionStore(
    (s) => s.regionSelectionPreset
  )
  const setRegionSelectionState = useHomeworldRegionSelectionStore(
    (s) => s.setRegionSelectionState
  )

  useEffect(() => {
    if (!overlaysReady) return
    if (useHomeworldRegionSelectionStore.getState().regionSelectionPreset !== 'all') {
      return
    }
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
}

export function useHomeworldRegionSelection({
  overlays,
}: UseHomeworldRegionSelectionOptions) {
  const regionSelectionPreset = useHomeworldRegionSelectionStore(
    (s) => s.regionSelectionPreset
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

  const { selectedSectorIndexes, selectedSectorIndexSet } =
    useEffectiveHomeworldSectorIndexes(overlays)

  const uiPreset = regionSelectionPresetForUi(regionSelectionPreset)

  const setUiPreset = useCallback(
    (preset: HomeworldRegionSelectionUiPreset) => {
      if (!isHomeworldRegionSelectionUiPreset(preset)) return
      if (preset === 'selected') {
        // Snapshot the current effective outline set (may re-derive from overlays
        // when leaving pinned/unpinned).
        setRegionSelectionState('selected', selectedSectorIndexes)
        return
      }
      // pinned / unpinned: derive-at-read; do not persist concrete indexes.
      setRegionSelectionState(preset, [])
    },
    [selectedSectorIndexes, setRegionSelectionState]
  )

  const toggleSectorIndex = useCallback(
    (sectorIndex: number) => {
      if (!Number.isInteger(sectorIndex) || sectorIndex < 0) return
      setRegionSelectionState(
        'selected',
        toggleSectorIndexInSelection(selectedSectorIndexes, sectorIndex)
      )
    },
    [selectedSectorIndexes, setRegionSelectionState]
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
  }
}
