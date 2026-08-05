/**
 * Owns homeworld region-selection writes and effective-index derivation for
 * Tile/Panel. Overlay bytes come from ``useHomeworldLocatorMapOverlays``
 * (same map-layer query as MapGraph registration) -- this hook does not fetch.
 *
 * Materialize effects (``all`` → selected) are owned solely by
 * ``useHomeworldRegionSelectionMaterialize`` -- call that once from MapGraph, fed from
 * homeworld sectors already present on combined ``data.regionOverlays``.
 *
 * Pinned/unpinned outline sets are derived at read time via
 * ``effectiveSelectedSectorIndexes``; do not continuously rewrite stored indexes
 * while those presets are active.
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
  /** True when the shared homeworld map query settled successfully. */
  overlaysReady: boolean
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
  const regionSelectionPreset = useHomeworldRegionSelectionStore(
    (s) => s.regionSelectionPreset
  )
  const setRegionSelectionState = useHomeworldRegionSelectionStore(
    (s) => s.setRegionSelectionState
  )

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
}

export function useHomeworldRegionSelection({
  overlays,
  overlaysReady,
}: UseHomeworldRegionSelectionOptions) {
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
        // Snapshot the current effective outline set (may re-derive from overlays
        // when leaving pinned/unpinned).
        const current = effectiveSelectedSectorIndexes(
          overlays,
          regionSelectionPreset,
          storedSelectedSectorIndexes
        )
        setRegionSelectionState('selected', current)
        return
      }
      // pinned / unpinned: derive-at-read; do not persist concrete indexes.
      setRegionSelectionState(preset, [])
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
