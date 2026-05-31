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

const turnTwoMap: CombinedMapData = {
  ...sampleMap,
  nodes: [{ id: 'base-map:1', label: 'A', x: 3, y: 4 }],
}

const emptyCombined: CombinedMapData = { ...sampleMap, nodes: [] }

const defaultScope = { gameId: 'g1', perspective: 1 }

describe('useRetainedMapDisplay', () => {
  it('returns combined when displayable', () => {
    const { result } = renderHook(() =>
      useRetainedMapDisplay({ combined: sampleMap, ...defaultScope, viewMode: 'map' })
    )
    expect(result.current.displayMapData).toBe(sampleMap)
    expect(result.current.retainDuringLoad).toBe(false)
  })

  it('retains prior map across empty combined within the same game and perspective', () => {
    const { result, rerender } = renderHook(
      ({
        combined,
        gameId,
        perspective,
      }: {
        combined: CombinedMapData | null
        gameId: string | null
        perspective: number | null
      }) => useRetainedMapDisplay({ combined, gameId, perspective, viewMode: 'map' }),
      { initialProps: { combined: sampleMap, ...defaultScope } }
    )

    rerender({ combined: emptyCombined, ...defaultScope })

    expect(result.current.displayMapData).toBe(sampleMap)
    expect(result.current.retainDuringLoad).toBe(true)
  })

  it('retains across turn step when game and perspective are unchanged', () => {
    const { result, rerender } = renderHook(
      ({
        combined,
        gameId,
        perspective,
      }: {
        combined: CombinedMapData | null
        gameId: string | null
        perspective: number | null
      }) => useRetainedMapDisplay({ combined, gameId, perspective, viewMode: 'map' }),
      { initialProps: { combined: sampleMap, ...defaultScope } }
    )

    rerender({ combined: emptyCombined, ...defaultScope })
    expect(result.current.displayMapData).toBe(sampleMap)
    expect(result.current.retainDuringLoad).toBe(true)

    rerender({ combined: turnTwoMap, ...defaultScope })
    expect(result.current.displayMapData).toBe(turnTwoMap)
    expect(result.current.retainDuringLoad).toBe(false)
  })

  it('clears retention after gameId changes', () => {
    const { result, rerender } = renderHook(
      ({
        combined,
        gameId,
        perspective,
      }: {
        combined: CombinedMapData | null
        gameId: string | null
        perspective: number | null
      }) => useRetainedMapDisplay({ combined, gameId, perspective, viewMode: 'map' }),
      { initialProps: { combined: sampleMap, ...defaultScope } }
    )

    rerender({ combined: emptyCombined, gameId: 'g2', perspective: 1 })

    expect(result.current.displayMapData).toBeNull()
    expect(result.current.retainDuringLoad).toBe(false)
  })

  it('clears retention after perspective changes', () => {
    const { result, rerender } = renderHook(
      ({
        combined,
        gameId,
        perspective,
      }: {
        combined: CombinedMapData | null
        gameId: string | null
        perspective: number | null
      }) => useRetainedMapDisplay({ combined, gameId, perspective, viewMode: 'map' }),
      { initialProps: { combined: sampleMap, ...defaultScope } }
    )

    rerender({ combined: emptyCombined, gameId: 'g1', perspective: 2 })

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
        useRetainedMapDisplay({ combined, ...defaultScope, viewMode }),
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
