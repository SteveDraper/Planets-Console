import { create } from 'zustand'

/** Pointer source for fleet location ring emphasis. Not persisted. */
export type FleetLocationRingEmphasisHover =
  | { kind: 'ring'; playerIds: readonly number[] }
  | { kind: 'sidebar'; playerId: number }

type FleetLocationRingEmphasisState = {
  hover: FleetLocationRingEmphasisHover | null
  setRingHover: (playerIds: readonly number[]) => void
  clearRingHover: () => void
  setSidebarHover: (playerId: number) => void
  clearSidebarHover: (playerId: number) => void
}

function samePlayerIds(left: readonly number[], right: readonly number[]): boolean {
  if (left.length !== right.length) {
    return false
  }
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index]) {
      return false
    }
  }
  return true
}

/** Ephemeral map/sidebar hover. Cleared on pointer leave. Not persisted. */
export const useFleetLocationRingEmphasisStore = create<FleetLocationRingEmphasisState>()(
  (set) => ({
    hover: null,
    setRingHover: (playerIds) => {
      const sorted = [...playerIds].sort((left, right) => left - right)
      set((state) => {
        if (state.hover?.kind === 'ring' && samePlayerIds(state.hover.playerIds, sorted)) {
          return state
        }
        return { hover: { kind: 'ring', playerIds: sorted } }
      })
    },
    clearRingHover: () => {
      set((state) => (state.hover?.kind === 'ring' ? { hover: null } : state))
    },
    setSidebarHover: (playerId) => {
      set((state) =>
        state.hover?.kind === 'sidebar' && state.hover.playerId === playerId
          ? state
          : { hover: { kind: 'sidebar', playerId } }
      )
    },
    clearSidebarHover: (playerId) => {
      set((state) =>
        state.hover?.kind === 'sidebar' && state.hover.playerId === playerId
          ? { hover: null }
          : state
      )
    },
  })
)
