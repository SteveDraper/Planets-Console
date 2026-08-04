import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { createLocalStorageOrMemoryStateStorage } from '../lib/browserPersistStorage'
import type { MapRegionOverlay } from '../api/mapRegionOverlayTypes'
import {
  allHomeworldSectorIndexes,
  defaultHomeworldRegionSelectionPreset,
  defaultShowEnvelopeOverlays,
  isHomeworldRegionSelectionPreset,
  sectorIndexesForPreset,
  toggleSectorIndexInSelection,
  type HomeworldRegionSelectionPreset,
} from '../analytics/homeworld-locator/homeworldRegionSelection'

const homeworldRegionSelectionPersistStorage = createLocalStorageOrMemoryStateStorage()

/** New preference key -- old ``planets-console-homeworld-region-display`` is ignored. */
export const HOMEWORLD_REGION_SELECTION_STORAGE_KEY =
  'planets-console-homeworld-region-selection'

const PERSIST_VERSION = 1

type HomeworldRegionSelectionState = {
  regionSelectionPreset: HomeworldRegionSelectionPreset
  selectedSectorIndexes: number[]
  showEnvelopeOverlays: boolean
  setRegionSelectionPreset: (
    preset: HomeworldRegionSelectionPreset,
    overlays?: readonly MapRegionOverlay[]
  ) => void
  setShowEnvelopeOverlays: (show: boolean) => void
  toggleSectorIndex: (sectorIndex: number) => void
  /**
   * When overlays are known: rewrite pinned/unpinned selection from overlay facts,
   * or seed empty selected set to all sector indexes.
   */
  syncSelectionWithOverlays: (overlays: readonly MapRegionOverlay[]) => void
}

type HomeworldRegionSelectionPersisted = Pick<
  HomeworldRegionSelectionState,
  'regionSelectionPreset' | 'selectedSectorIndexes' | 'showEnvelopeOverlays'
>

function parseSelectedSectorIndexes(value: unknown): number[] {
  if (!Array.isArray(value)) return []
  const indexes: number[] = []
  for (const entry of value) {
    if (typeof entry !== 'number' || !Number.isInteger(entry) || entry < 0) continue
    indexes.push(entry)
  }
  return [...new Set(indexes)].sort((a, b) => a - b)
}

function migratePersistedState(persisted: unknown): HomeworldRegionSelectionPersisted {
  const raw = (persisted ?? {}) as {
    regionSelectionPreset?: unknown
    selectedSectorIndexes?: unknown
    showEnvelopeOverlays?: unknown
  }
  return {
    regionSelectionPreset: isHomeworldRegionSelectionPreset(raw.regionSelectionPreset)
      ? raw.regionSelectionPreset
      : defaultHomeworldRegionSelectionPreset(),
    selectedSectorIndexes: parseSelectedSectorIndexes(raw.selectedSectorIndexes),
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
      selectedSectorIndexes: [],
      showEnvelopeOverlays: defaultShowEnvelopeOverlays(),
      setRegionSelectionPreset: (preset, overlays) => {
        if (!isHomeworldRegionSelectionPreset(preset)) return
        if (preset === 'selected') {
          set({ regionSelectionPreset: 'selected' })
          return
        }
        if (overlays == null) {
          set({ regionSelectionPreset: preset })
          return
        }
        set({
          regionSelectionPreset: preset,
          selectedSectorIndexes: sectorIndexesForPreset(overlays, preset),
        })
      },
      setShowEnvelopeOverlays: (show) => {
        set({ showEnvelopeOverlays: show })
      },
      toggleSectorIndex: (sectorIndex) => {
        if (!Number.isInteger(sectorIndex) || sectorIndex < 0) return
        set({
          regionSelectionPreset: 'selected',
          selectedSectorIndexes: toggleSectorIndexInSelection(
            get().selectedSectorIndexes,
            sectorIndex
          ),
        })
      },
      syncSelectionWithOverlays: (overlays) => {
        const { regionSelectionPreset, selectedSectorIndexes } = get()
        if (regionSelectionPreset === 'pinned' || regionSelectionPreset === 'unpinned') {
          set({
            selectedSectorIndexes: sectorIndexesForPreset(overlays, regionSelectionPreset),
          })
          return
        }
        if (selectedSectorIndexes.length === 0) {
          const all = allHomeworldSectorIndexes(overlays)
          if (all.length > 0) {
            set({ selectedSectorIndexes: all })
          }
        }
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
      migrate: (persisted) => migratePersistedState(persisted),
    }
  )
)
