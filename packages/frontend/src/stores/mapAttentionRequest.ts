/**
 * Cross-tree bus for map attention intents (sidebar → map, or in-map clicks).
 * The MapAttentionOrchestrator inside React Flow owns pan + pulse lifetime.
 */

import { create } from 'zustand'
import type { MapAttentionRequest, MapAttentionSpec } from '../lib/mapAttention'

type MapAttentionRequestState = {
  pending: MapAttentionRequest | null
  requestAttention: (spec: MapAttentionSpec) => void
  clearAttention: () => void
}

/** Monotonic token so same-ms clicks never collide. */
let nextAttentionToken = 0

export const useMapAttentionRequestStore = create<MapAttentionRequestState>()((set) => ({
  pending: null,
  requestAttention: (spec) =>
    set({
      pending: { ...spec, token: ++nextAttentionToken },
    }),
  clearAttention: () => set({ pending: null }),
}))

/** Fire-and-forget attention request (panel, wormhole click, tests). */
export function requestMapAttention(spec: MapAttentionSpec): void {
  useMapAttentionRequestStore.getState().requestAttention(spec)
}
