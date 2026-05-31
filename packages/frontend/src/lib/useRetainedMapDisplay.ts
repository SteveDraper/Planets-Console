import { useEffect, useRef } from 'react'
import type { CombinedMapData } from '../api/bff'
import { hasDisplayableMapData, shouldRetainMapDuringLoad } from './mapDisplayRetention'

export type UseRetainedMapDisplayInput = {
  combined: CombinedMapData | null | undefined
  gameId: string | null
  viewMode: 'tabular' | 'map'
}

export type UseRetainedMapDisplayResult = {
  displayMapData: CombinedMapData | null
  retainDuringLoad: boolean
}

/**
 * Retains the last displayable map across turn/query-key changes within a game.
 * The ref handles cross-turn query-key changes; keepPreviousData on map queries
 * (in MainArea) handles same-key refetch without clearing the pane.
 */
export function useRetainedMapDisplay({
  combined,
  gameId,
  viewMode,
}: UseRetainedMapDisplayInput): UseRetainedMapDisplayResult {
  const retainedMapDataRef = useRef<CombinedMapData | null>(null)
  const retainedMapGameIdRef = useRef<string | null>(null)

  useEffect(() => {
    if (gameId !== retainedMapGameIdRef.current) {
      retainedMapDataRef.current = null
      retainedMapGameIdRef.current = gameId
    }
  }, [gameId])

  useEffect(() => {
    if (hasDisplayableMapData(combined)) {
      retainedMapDataRef.current = combined
    }
  }, [combined])

  const retainDuringLoad = shouldRetainMapDuringLoad(viewMode, retainedMapDataRef.current)
  const displayMapData = hasDisplayableMapData(combined)
    ? combined
    : retainedMapDataRef.current

  return { displayMapData, retainDuringLoad }
}
