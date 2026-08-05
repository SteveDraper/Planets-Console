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

export const useMapAttentionRequestStore = create<MapAttentionRequestState>()((set) => ({
  pending: null,
  requestAttention: (spec) =>
    set({
      pending: { ...spec, token: Date.now() },
    }),
  clearAttention: () => set({ pending: null }),
}))

/** Fire-and-forget attention request (panel, wormhole click, tests). */
export function requestMapAttention(spec: MapAttentionSpec): void {
  useMapAttentionRequestStore.getState().requestAttention(spec)
}
