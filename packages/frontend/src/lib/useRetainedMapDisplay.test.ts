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

const idleMapLoad = {
  turnDataReady: true,
  turnEnsurePending: false,
  mapPending: false,
  mapHasError: false,
  mapHasAnyData: true,
}

const initialMapLoad = {
  turnDataReady: true,
  turnEnsurePending: false,
  mapPending: true,
  mapHasError: false,
  mapHasAnyData: false,
}

describe('useRetainedMapDisplay', () => {
  it('returns combined when displayable', () => {
    const { result } = renderHook(() =>
      useRetainedMapDisplay({
        combined: sampleMap,
        ...defaultScope,
        viewMode: 'map',
        ...idleMapLoad,
      })
    )
    expect(result.current.displayMapData).toBe(sampleMap)
    expect(result.current.retainDuringLoad).toBe(false)
    expect(result.current.mapShellPhase).toBe('ready')
  })

  it('reports full-loading on initial map load with no retained frame', () => {
    const { result } = renderHook(() =>
      useRetainedMapDisplay({
        combined: emptyCombined,
        ...defaultScope,
        viewMode: 'map',
        ...initialMapLoad,
      })
    )
    expect(result.current.displayMapData).toBeNull()
    expect(result.current.retainDuringLoad).toBe(false)
    expect(result.current.mapShellPhase).toBe('full-loading')
  })

  it('retains prior map across empty combined within the same game and perspective', () => {
    const { result, rerender } = renderHook(
      ({
        combined,
        gameId,
        perspective,
        mapPending,
        mapHasAnyData,
      }: {
        combined: CombinedMapData | null
        gameId: string | null
        perspective: number | null
        mapPending: boolean
        mapHasAnyData: boolean
      }) =>
        useRetainedMapDisplay({
          combined,
          gameId,
          perspective,
          viewMode: 'map',
          turnDataReady: true,
          turnEnsurePending: false,
          mapPending,
          mapHasError: false,
          mapHasAnyData,
        }),
      {
        initialProps: {
          combined: sampleMap,
          ...defaultScope,
          mapPending: false,
          mapHasAnyData: true,
        },
      }
    )

    rerender({
      combined: emptyCombined,
      ...defaultScope,
      mapPending: true,
      mapHasAnyData: false,
    })

    expect(result.current.displayMapData).toBe(sampleMap)
    expect(result.current.retainDuringLoad).toBe(true)
    expect(result.current.mapShellPhase).toBe('retained')
  })

  it('retains across turn step when game and perspective are unchanged', () => {
    const { result, rerender } = renderHook(
      ({
        combined,
        gameId,
        perspective,
        mapPending,
        mapHasAnyData,
      }: {
        combined: CombinedMapData | null
        gameId: string | null
        perspective: number | null
        mapPending: boolean
        mapHasAnyData: boolean
      }) =>
        useRetainedMapDisplay({
          combined,
          gameId,
          perspective,
          viewMode: 'map',
          turnDataReady: true,
          turnEnsurePending: false,
          mapPending,
          mapHasError: false,
          mapHasAnyData,
        }),
      {
        initialProps: {
          combined: sampleMap,
          ...defaultScope,
          mapPending: false,
          mapHasAnyData: true,
        },
      }
    )

    rerender({
      combined: emptyCombined,
      ...defaultScope,
      mapPending: true,
      mapHasAnyData: false,
    })
    expect(result.current.displayMapData).toBe(sampleMap)
    expect(result.current.retainDuringLoad).toBe(true)
    expect(result.current.mapShellPhase).toBe('retained')

    rerender({
      combined: turnTwoMap,
      ...defaultScope,
      mapPending: false,
      mapHasAnyData: true,
    })
    expect(result.current.displayMapData).toBe(turnTwoMap)
    expect(result.current.retainDuringLoad).toBe(false)
    expect(result.current.mapShellPhase).toBe('ready')
  })

  it('retains only within the current game and perspective key', () => {
    const otherGameMap: CombinedMapData = {
      ...sampleMap,
      nodes: [{ id: 'base-map:99', label: 'Z', x: 9, y: 9 }],
    }

    const { result, rerender } = renderHook(
      ({
        combined,
        gameId,
        perspective,
        mapPending,
        mapHasAnyData,
      }: {
        combined: CombinedMapData | null
        gameId: string | null
        perspective: number | null
        mapPending: boolean
        mapHasAnyData: boolean
      }) =>
        useRetainedMapDisplay({
          combined,
          gameId,
          perspective,
          viewMode: 'map',
          turnDataReady: true,
          turnEnsurePending: false,
          mapPending,
          mapHasError: false,
          mapHasAnyData,
        }),
      {
        initialProps: {
          combined: sampleMap,
          ...defaultScope,
          mapPending: false,
          mapHasAnyData: true,
        },
      }
    )

    rerender({
      combined: otherGameMap,
      gameId: 'g2',
      perspective: 1,
      mapPending: false,
      mapHasAnyData: true,
    })
    expect(result.current.displayMapData).toBe(otherGameMap)

    rerender({
      combined: emptyCombined,
      gameId: 'g2',
      perspective: 1,
      mapPending: true,
      mapHasAnyData: false,
    })
    expect(result.current.displayMapData).toBe(otherGameMap)
    expect(result.current.displayMapData).not.toBe(sampleMap)
    expect(result.current.retainDuringLoad).toBe(true)
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
      }) =>
        useRetainedMapDisplay({
          combined,
          gameId,
          perspective,
          viewMode: 'map',
          ...initialMapLoad,
        }),
      { initialProps: { combined: sampleMap, ...defaultScope } }
    )

    rerender({ combined: emptyCombined, gameId: 'g2', perspective: 1 })

    expect(result.current.displayMapData).toBeNull()
    expect(result.current.retainDuringLoad).toBe(false)
    expect(result.current.mapShellPhase).toBe('full-loading')
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
      }) =>
        useRetainedMapDisplay({
          combined,
          gameId,
          perspective,
          viewMode: 'map',
          ...initialMapLoad,
        }),
      { initialProps: { combined: sampleMap, ...defaultScope } }
    )

    rerender({ combined: emptyCombined, gameId: 'g1', perspective: 2 })

    expect(result.current.displayMapData).toBeNull()
    expect(result.current.retainDuringLoad).toBe(false)
    expect(result.current.mapShellPhase).toBe('full-loading')
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
        useRetainedMapDisplay({
          combined,
          ...defaultScope,
          viewMode,
          turnDataReady: true,
          turnEnsurePending: false,
          mapPending: true,
          mapHasError: false,
          mapHasAnyData: false,
        }),
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
    expect(result.current.mapShellPhase).toBe('ready')
  })

  it('keeps phase retained (not full-loading) when turn ensure fails after a prior frame', () => {
    // Hook phase stays retained; MainArea.tsx replaces the map pane with a turn-error placeholder
    // when turnEnsureIsError && !turnDataReady (see design-frontend-and-backend-state.md).
    const { result, rerender } = renderHook(
      ({
        combined,
        turnDataReady,
        turnEnsurePending,
        mapPending,
        mapHasAnyData,
      }: {
        combined: CombinedMapData | null
        turnDataReady: boolean
        turnEnsurePending: boolean
        mapPending: boolean
        mapHasAnyData: boolean
      }) =>
        useRetainedMapDisplay({
          combined,
          ...defaultScope,
          viewMode: 'map',
          turnDataReady,
          turnEnsurePending,
          mapPending,
          mapHasError: false,
          mapHasAnyData,
        }),
      {
        initialProps: {
          combined: sampleMap,
          turnDataReady: true,
          turnEnsurePending: false,
          mapPending: false,
          mapHasAnyData: true,
        },
      }
    )

    rerender({
      combined: emptyCombined,
      turnDataReady: false,
      turnEnsurePending: false,
      mapPending: true,
      mapHasAnyData: false,
    })

    expect(result.current.displayMapData).toBe(sampleMap)
    expect(result.current.retainDuringLoad).toBe(true)
    expect(result.current.mapShellPhase).toBe('retained')
  })

  it('keeps retained map visible while turn ensure runs in map mode', () => {
    const { result, rerender } = renderHook(
      ({
        combined,
        turnDataReady,
        turnEnsurePending,
        mapPending,
        mapHasAnyData,
      }: {
        combined: CombinedMapData | null
        turnDataReady: boolean
        turnEnsurePending: boolean
        mapPending: boolean
        mapHasAnyData: boolean
      }) =>
        useRetainedMapDisplay({
          combined,
          ...defaultScope,
          viewMode: 'map',
          turnDataReady,
          turnEnsurePending,
          mapPending,
          mapHasError: false,
          mapHasAnyData,
        }),
      {
        initialProps: {
          combined: sampleMap,
          turnDataReady: true,
          turnEnsurePending: false,
          mapPending: false,
          mapHasAnyData: true,
        },
      }
    )

    rerender({
      combined: emptyCombined,
      turnDataReady: false,
      turnEnsurePending: true,
      mapPending: true,
      mapHasAnyData: false,
    })

    expect(result.current.displayMapData).toBe(sampleMap)
    expect(result.current.mapShellPhase).toBe('retained')
  })
})
