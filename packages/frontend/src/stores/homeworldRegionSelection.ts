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

const PERSIST_VERSION = 2

type HomeworldRegionSelectionState = {
  regionSelectionPreset: HomeworldRegionSelectionPreset
  /** ``null`` = never seeded (sync fills all once); ``[]`` = user cleared every sector. */
  selectedSectorIndexes: number[] | null
  showEnvelopeOverlays: boolean
  setRegionSelectionPreset: (
    preset: HomeworldRegionSelectionPreset,
    overlays?: readonly MapRegionOverlay[]
  ) => void
  setShowEnvelopeOverlays: (show: boolean) => void
  toggleSectorIndex: (sectorIndex: number) => void
  /**
   * When overlays are known: rewrite pinned/unpinned selection from overlay facts,
   * or seed uninitialized selection to all sector indexes once.
   */
  syncSelectionWithOverlays: (overlays: readonly MapRegionOverlay[]) => void
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
  // v1 conflated uninitialized with ``[]``; upgrade treats legacy empty as never seeded.
  if (version < PERSIST_VERSION && selectedSectorIndexes?.length === 0) {
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
            get().selectedSectorIndexes ?? [],
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
        if (selectedSectorIndexes === null) {
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
      migrate: (persisted, version) => migratePersistedState(persisted, version),
    }
  )
)
