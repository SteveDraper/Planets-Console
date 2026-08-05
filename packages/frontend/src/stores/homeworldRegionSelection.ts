import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { createLocalStorageOrMemoryStateStorage } from '../lib/browserPersistStorage'
import type { MapRegionOverlay } from '../api/mapRegionOverlayTypes'
import {
  defaultHomeworldRegionSelectionPreset,
  defaultShowEnvelopeOverlays,
  effectiveSelectedSectorIndexes,
  isHomeworldRegionSelectionPreset,
  toggleSectorIndexInSelection,
  type HomeworldRegionSelectionPreset,
} from '../analytics/homeworld-locator/homeworldRegionSelection'

const homeworldRegionSelectionPersistStorage = createLocalStorageOrMemoryStateStorage()

/** New preference key -- old ``planets-console-homeworld-region-display`` is ignored. */
export const HOMEWORLD_REGION_SELECTION_STORAGE_KEY =
  'planets-console-homeworld-region-selection'

const PERSIST_VERSION = 3

type HomeworldRegionSelectionState = {
  regionSelectionPreset: HomeworldRegionSelectionPreset
  /**
   * Meaningful only when preset is ``selected``.
   * ``null`` = all current homeworld sectors; ``number[]`` = explicit multi-select
   * (including ``[]`` = none). Ignored while preset is pinned/unpinned (derived at read).
   */
  selectedSectorIndexes: number[] | null
  showEnvelopeOverlays: boolean
  setRegionSelectionPreset: (
    preset: HomeworldRegionSelectionPreset,
    overlays: readonly MapRegionOverlay[]
  ) => void
  setShowEnvelopeOverlays: (show: boolean) => void
  /**
   * Force ``selected`` and toggle one sector against the effective current set
   * (pinned/unpinned derived, or stored/all for selected).
   */
  toggleSectorIndex: (
    sectorIndex: number,
    overlays: readonly MapRegionOverlay[]
  ) => void
}

type HomeworldRegionSelectionPersisted = Pick<
  HomeworldRegionSelectionState,
  'regionSelectionPreset' | 'selectedSectorIndexes' | 'showEnvelopeOverlays'
>

function parseSelectedSectorIndexes(value: unknown): number[] | null {
  if (value === null || value === undefined) return null
  if (!Array.isArray(value)) return null
  if (value.length === 0) return []
  const indexes: number[] = []
  for (const entry of value) {
    if (typeof entry !== 'number' || !Number.isInteger(entry) || entry < 0) continue
    indexes.push(entry)
  }
  return [...new Set(indexes)].sort((a, b) => a - b)
}

function migratePersistedState(
  persisted: unknown,
  version: number
): HomeworldRegionSelectionPersisted {
  const raw = (persisted ?? {}) as {
    regionSelectionPreset?: unknown
    selectedSectorIndexes?: unknown
    showEnvelopeOverlays?: unknown
  }
  let selectedSectorIndexes = parseSelectedSectorIndexes(raw.selectedSectorIndexes)
  // v1 conflated uninitialized with ``[]``; upgrade treats legacy empty as default-all.
  if (version < 2 && selectedSectorIndexes?.length === 0) {
    selectedSectorIndexes = null
  }
  // v2 wrote concrete indexes when applying Pinned/Unpinned (and MapGraph sync).
  // Those arrays stuck under Selected after switching presets. v3 drops them so
  // Selected + null again means all current sectors.
  if (version < PERSIST_VERSION) {
    selectedSectorIndexes = null
  }
  return {
    regionSelectionPreset: isHomeworldRegionSelectionPreset(raw.regionSelectionPreset)
      ? raw.regionSelectionPreset
      : defaultHomeworldRegionSelectionPreset(),
    selectedSectorIndexes,
    showEnvelopeOverlays:
      typeof raw.showEnvelopeOverlays === 'boolean'
        ? raw.showEnvelopeOverlays
        : defaultShowEnvelopeOverlays(),
  }
}

export const useHomeworldRegionSelectionStore = create<HomeworldRegionSelectionState>()(
  persist(
    (set, get) => ({
      regionSelectionPreset: defaultHomeworldRegionSelectionPreset(),
      selectedSectorIndexes: null,
      showEnvelopeOverlays: defaultShowEnvelopeOverlays(),
      setRegionSelectionPreset: (preset, overlays) => {
        if (!isHomeworldRegionSelectionPreset(preset)) return
        const { regionSelectionPreset, selectedSectorIndexes } = get()
        if (
          preset === 'selected' &&
          (regionSelectionPreset === 'pinned' || regionSelectionPreset === 'unpinned')
        ) {
          set({
            regionSelectionPreset: preset,
            selectedSectorIndexes: effectiveSelectedSectorIndexes(
              overlays,
              regionSelectionPreset,
              selectedSectorIndexes
            ),
          })
          return
        }
        set({ regionSelectionPreset: preset })
      },
      setShowEnvelopeOverlays: (show) => {
        set({ showEnvelopeOverlays: show })
      },
      toggleSectorIndex: (sectorIndex, overlays) => {
        if (!Number.isInteger(sectorIndex) || sectorIndex < 0) return
        const { regionSelectionPreset, selectedSectorIndexes } = get()
        const current = effectiveSelectedSectorIndexes(
          overlays,
          regionSelectionPreset,
          selectedSectorIndexes
        )
        set({
          regionSelectionPreset: 'selected',
          selectedSectorIndexes: toggleSectorIndexInSelection(current, sectorIndex),
        })
      },
    }),
    {
      name: HOMEWORLD_REGION_SELECTION_STORAGE_KEY,
      version: PERSIST_VERSION,
      storage: createJSONStorage(() => homeworldRegionSelectionPersistStorage),
      partialize: (state) => ({
        regionSelectionPreset: state.regionSelectionPreset,
        selectedSectorIndexes: state.selectedSectorIndexes,
        showEnvelopeOverlays: state.showEnvelopeOverlays,
      }),
      migrate: (persisted, version) => migratePersistedState(persisted, version),
    }
  )
)
