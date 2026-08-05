import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { createLocalStorageOrMemoryStateStorage } from '../lib/browserPersistStorage'
import {
  defaultHomeworldRegionSelectionPreset,
  defaultShowEnvelopeOverlays,
  isHomeworldRegionSelectionPreset,
  type HomeworldRegionSelectionPreset,
} from '../lib/homeworldRegionSelection'

const homeworldRegionSelectionPersistStorage = createLocalStorageOrMemoryStateStorage()

/** New preference key -- old ``planets-console-homeworld-region-display`` is ignored. */
export const HOMEWORLD_REGION_SELECTION_STORAGE_KEY =
  'planets-console-homeworld-region-selection'

/** v4: concrete indexes + init-only ``all`` preset (replaces null = all under selected). */
const PERSIST_VERSION = 4

type HomeworldRegionSelectionState = {
  regionSelectionPreset: HomeworldRegionSelectionPreset
  /**
   * Concrete outline multi-select under ``selected`` (including ``[]`` = none).
   * Empty under init-only ``all`` until overlays-ready materialize, and under
   * ``pinned`` / ``unpinned`` (those presets derive indexes at read time).
   */
  selectedSectorIndexes: number[]
  showEnvelopeOverlays: boolean
  /** Replace preset + indexes together (callers decide indexes; store stays dumb). */
  setRegionSelectionState: (
    preset: HomeworldRegionSelectionPreset,
    selectedSectorIndexes: readonly number[]
  ) => void
  setShowEnvelopeOverlays: (show: boolean) => void
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

function migratePersistedState(
  persisted: unknown,
  version: number
): HomeworldRegionSelectionPersisted {
  const raw = (persisted ?? {}) as {
    regionSelectionPreset?: unknown
    selectedSectorIndexes?: unknown
    showEnvelopeOverlays?: unknown
  }

  let regionSelectionPreset: HomeworldRegionSelectionPreset =
    isHomeworldRegionSelectionPreset(raw.regionSelectionPreset)
      ? raw.regionSelectionPreset
      : defaultHomeworldRegionSelectionPreset()

  let selectedSectorIndexes: number[]
  if (version < 4) {
    // v1–v3: ``null`` = all under Selected. Concrete arrays under Selected stay.
    const rawIndexes = raw.selectedSectorIndexes
    if (rawIndexes === null || rawIndexes === undefined) {
      if (regionSelectionPreset === 'selected') {
        regionSelectionPreset = 'all'
      }
      selectedSectorIndexes = []
    } else {
      selectedSectorIndexes = parseSelectedSectorIndexes(rawIndexes)
      // v1 conflated uninitialized with ``[]`` under Selected.
      if (
        version < 2 &&
        selectedSectorIndexes.length === 0 &&
        regionSelectionPreset === 'selected'
      ) {
        regionSelectionPreset = 'all'
      }
    }
  } else {
    selectedSectorIndexes = parseSelectedSectorIndexes(raw.selectedSectorIndexes)
  }

  if (regionSelectionPreset === 'all') {
    selectedSectorIndexes = []
  }

  return {
    regionSelectionPreset,
    selectedSectorIndexes,
    showEnvelopeOverlays:
      typeof raw.showEnvelopeOverlays === 'boolean'
        ? raw.showEnvelopeOverlays
        : defaultShowEnvelopeOverlays(),
  }
}

export const useHomeworldRegionSelectionStore = create<HomeworldRegionSelectionState>()(
  persist(
    (set) => ({
      regionSelectionPreset: defaultHomeworldRegionSelectionPreset(),
      selectedSectorIndexes: [],
      showEnvelopeOverlays: defaultShowEnvelopeOverlays(),
      setRegionSelectionState: (preset, selectedSectorIndexes) => {
        if (!isHomeworldRegionSelectionPreset(preset)) return
        set({
          regionSelectionPreset: preset,
          selectedSectorIndexes: [...selectedSectorIndexes].sort((a, b) => a - b),
        })
      },
      setShowEnvelopeOverlays: (show) => {
        set({ showEnvelopeOverlays: show })
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
