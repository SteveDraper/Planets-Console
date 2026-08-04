import { afterEach, describe, expect, it } from 'vitest'
import { CELL_CENTER_OFFSET } from '../../components/map-graph/geometry'
import { useHomeworldCandidateFlashStore } from '../../stores/homeworldCandidateFlash'
import { useHomeworldLocatorSelectionStore } from '../../stores/homeworldLocatorSelection'
import {
  resolveHomeworldCandidatePan,
  selectHomeworldCandidateForMapAttention,
} from './homeworldCandidateAttention'

describe('selectHomeworldCandidateForMapAttention', () => {
  afterEach(() => {
    useHomeworldLocatorSelectionStore.getState().clearSelection()
    useHomeworldCandidateFlashStore.getState().clearFlash()
  })

  it('sets planet selection and a flash target', () => {
    selectHomeworldCandidateForMapAttention(42)
    expect(useHomeworldLocatorSelectionStore.getState().selection).toEqual({
      kind: 'planet',
      planetId: 42,
    })
    const flash = useHomeworldCandidateFlashStore.getState().flashTarget
    expect(flash?.planetId).toBe(42)
    expect(typeof flash?.token).toBe('number')
  })

  it('re-flashing the same planet bumps the flash token', () => {
    selectHomeworldCandidateForMapAttention(7)
    const first = useHomeworldCandidateFlashStore.getState().flashTarget!.token
    selectHomeworldCandidateForMapAttention(7)
    const second = useHomeworldCandidateFlashStore.getState().flashTarget!.token
    expect(second).toBeGreaterThanOrEqual(first)
  })
})

describe('resolveHomeworldCandidatePan', () => {
  const markers = [{ planetId: 10, x: 100, y: 200 }] as const
  const viewport = { x: 400, y: 300, zoom: 1, width: 800, height: 600 }

  it('returns null when the planet has no marker', () => {
    expect(resolveHomeworldCandidatePan(99, markers, viewport)).toBeNull()
  })

  it('reports needsPan false when the marker center is on-screen', () => {
    // flow center: (100.5, -(200.5)); with tx/ty 400/300 at zoom 1 → pane ~ (500.5, 99.5)
    const resolved = resolveHomeworldCandidatePan(10, markers, viewport)
    expect(resolved).not.toBeNull()
    expect(resolved!.flowX).toBeCloseTo(100 + CELL_CENTER_OFFSET)
    expect(resolved!.flowY).toBeCloseTo(-(200 + CELL_CENTER_OFFSET))
    expect(resolved!.needsPan).toBe(false)
  })

  it('reports needsPan true when the marker is off-screen', () => {
    const resolved = resolveHomeworldCandidatePan(10, markers, {
      ...viewport,
      x: -10_000,
      y: -10_000,
    })
    expect(resolved?.needsPan).toBe(true)
  })
})
