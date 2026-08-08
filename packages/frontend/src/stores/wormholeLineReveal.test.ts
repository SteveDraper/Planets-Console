import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  resetWormholeLineRevealStore,
  useWormholeLineRevealStore,
  WORMHOLE_LINE_REVEAL_CLEAR_MS,
} from './wormholeLineReveal'

describe('useWormholeLineRevealStore', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    resetWormholeLineRevealStore()
  })

  afterEach(() => {
    resetWormholeLineRevealStore()
    vi.useRealTimers()
  })

  it('revealAt sets wormholeLineRevealKey from map cell', () => {
    useWormholeLineRevealStore.getState().revealAt(100, 200)
    expect(useWormholeLineRevealStore.getState().wormholeLineRevealKey).toBe(
      '100,200'
    )
  })

  it('scheduleClear clears the key after the debounce', () => {
    useWormholeLineRevealStore.getState().revealAt(1, 2)
    useWormholeLineRevealStore.getState().scheduleClear()
    expect(useWormholeLineRevealStore.getState().wormholeLineRevealKey).toBe(
      '1,2'
    )
    vi.advanceTimersByTime(WORMHOLE_LINE_REVEAL_CLEAR_MS - 1)
    expect(useWormholeLineRevealStore.getState().wormholeLineRevealKey).toBe(
      '1,2'
    )
    vi.advanceTimersByTime(1)
    expect(useWormholeLineRevealStore.getState().wormholeLineRevealKey).toBe(
      null
    )
  })

  it('cancelClear prevents a pending clear', () => {
    useWormholeLineRevealStore.getState().revealAt(3, 4)
    useWormholeLineRevealStore.getState().scheduleClear()
    useWormholeLineRevealStore.getState().cancelClear()
    vi.advanceTimersByTime(WORMHOLE_LINE_REVEAL_CLEAR_MS)
    expect(useWormholeLineRevealStore.getState().wormholeLineRevealKey).toBe(
      '3,4'
    )
  })

  it('revealAt cancels a pending clear', () => {
    useWormholeLineRevealStore.getState().revealAt(5, 6)
    useWormholeLineRevealStore.getState().scheduleClear()
    useWormholeLineRevealStore.getState().revealAt(7, 8)
    vi.advanceTimersByTime(WORMHOLE_LINE_REVEAL_CLEAR_MS)
    expect(useWormholeLineRevealStore.getState().wormholeLineRevealKey).toBe(
      '7,8'
    )
  })

  it('exports a 120ms clear debounce', () => {
    expect(WORMHOLE_LINE_REVEAL_CLEAR_MS).toBe(120)
  })
})
