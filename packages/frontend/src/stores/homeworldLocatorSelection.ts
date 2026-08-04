/**
 * Ephemeral homeworld locator UI selection (panel/table ↔ map highlight).
 */

import { create } from 'zustand'

export type HomeworldLocatorSelection =
  | { kind: 'planet'; planetId: number }
  | { kind: 'sector'; sectorIndex: number }
  | null

type HomeworldLocatorSelectionState = {
  selection: HomeworldLocatorSelection
  setSelection: (selection: HomeworldLocatorSelection) => void
  clearSelection: () => void
}

export const useHomeworldLocatorSelectionStore = create<HomeworldLocatorSelectionState>()(
  (set) => ({
    selection: null,
    setSelection: (selection) => set({ selection }),
    clearSelection: () => set({ selection: null }),
  })
)
