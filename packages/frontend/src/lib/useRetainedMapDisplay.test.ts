import { renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { CombinedMapData } from '../api/bff'
import { useRetainedMapDisplay } from './useRetainedMapDisplay'

const sampleMap: CombinedMapData = {
  nodes: [{ id: 'base-map:1', label: 'A', x: 1, y: 2 }],
  edges: [],
  routeWaypoints: [],
  overlayCircles: [],
  wormholeUnknownEntrances: [],
}

const emptyCombined: CombinedMapData = { ...sampleMap, nodes: [] }

describe('useRetainedMapDisplay', () => {
  it('returns combined when displayable', () => {
    const { result } = renderHook(() =>
      useRetainedMapDisplay({ combined: sampleMap, gameId: 'g1', viewMode: 'map' })
    )
    expect(result.current.displayMapData).toBe(sampleMap)
    expect(result.current.retainDuringLoad).toBe(false)
  })

  it('retains prior map across empty combined within the same game', () => {
    const { result, rerender } = renderHook(
      ({ combined, gameId }: { combined: CombinedMapData | null; gameId: string | null }) =>
        useRetainedMapDisplay({ combined, gameId, viewMode: 'map' }),
      { initialProps: { combined: sampleMap, gameId: 'g1' } }
    )

    rerender({ combined: emptyCombined, gameId: 'g1' })

    expect(result.current.displayMapData).toBe(sampleMap)
    expect(result.current.retainDuringLoad).toBe(true)
  })

  it('clears retention after gameId changes', () => {
    const { result, rerender } = renderHook(
      ({ combined, gameId }: { combined: CombinedMapData | null; gameId: string | null }) =>
        useRetainedMapDisplay({ combined, gameId, viewMode: 'map' }),
      { initialProps: { combined: sampleMap, gameId: 'g1' } }
    )

    rerender({ combined: emptyCombined, gameId: 'g2' })
    rerender({ combined: emptyCombined, gameId: 'g2' })

    expect(result.current.displayMapData).toBeNull()
    expect(result.current.retainDuringLoad).toBe(false)
  })

  it('does not retain during load in tabular mode', () => {
    const { result, rerender } = renderHook(
      ({
        combined,
        viewMode,
      }: {
        combined: CombinedMapData | null
        viewMode: 'tabular' | 'map'
      }) =>
        useRetainedMapDisplay({ combined, gameId: 'g1', viewMode }),
      {
        initialProps: {
          combined: sampleMap,
          viewMode: 'map' as 'tabular' | 'map',
        },
      }
    )

    rerender({ combined: emptyCombined, viewMode: 'tabular' })

    expect(result.current.displayMapData).toBe(sampleMap)
    expect(result.current.retainDuringLoad).toBe(false)
  })
})
