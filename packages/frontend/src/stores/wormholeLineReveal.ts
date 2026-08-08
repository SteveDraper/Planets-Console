/**
 * On-hover wormhole line reveal for Stellar Cartography paint.
 *
 * Owned here (neutral store) so map-interaction can drive reveal from hit-test
 * without importing map-graph, and MapGraph can subscribe for display filtering.
 */

import { create } from 'zustand'
import { wormholeMapCellKey } from '../lib/wormholeEndpointHover'

export const WORMHOLE_LINE_REVEAL_CLEAR_MS = 120

type WormholeLineRevealState = {
  wormholeLineRevealKey: string | null
  revealAt: (mapX: number, mapY: number) => void
  scheduleClear: () => void
  cancelClear: () => void
}

let clearTimer: ReturnType<typeof setTimeout> | null = null

function clearPendingTimer(): void {
  if (clearTimer == null) return
  clearTimeout(clearTimer)
  clearTimer = null
}

export const useWormholeLineRevealStore = create<WormholeLineRevealState>()((set) => ({
  wormholeLineRevealKey: null,
  revealAt: (mapX, mapY) => {
    clearPendingTimer()
    set({ wormholeLineRevealKey: wormholeMapCellKey(mapX, mapY) })
  },
  scheduleClear: () => {
    clearPendingTimer()
    clearTimer = setTimeout(() => {
      clearTimer = null
      set({ wormholeLineRevealKey: null })
    }, WORMHOLE_LINE_REVEAL_CLEAR_MS)
  },
  cancelClear: () => {
    clearPendingTimer()
  },
}))

/** Reset store + pending timer (tests). */
export function resetWormholeLineRevealStore(): void {
  clearPendingTimer()
  useWormholeLineRevealStore.setState({ wormholeLineRevealKey: null })
}
