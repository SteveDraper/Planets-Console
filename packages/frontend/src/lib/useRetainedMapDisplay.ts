import { useRef } from 'react'
import type { CombinedMapData } from '../api/bff'
import { hasDisplayableMapData, shouldRetainMapDuringLoad } from './mapDisplayRetention'

export type MapDisplayRetentionKey = {
  gameId: string
  perspective: number
}

export type UseRetainedMapDisplayInput = {
  combined: CombinedMapData | null | undefined
  gameId: string | null
  perspective: number | null
  viewMode: 'tabular' | 'map'
}

export type UseRetainedMapDisplayResult = {
  displayMapData: CombinedMapData | null
  retainDuringLoad: boolean
}

function mapDisplayRetentionKey(
  gameId: string | null,
  perspective: number | null
): MapDisplayRetentionKey | null {
  if (gameId == null || perspective == null) {
    return null
  }
  return { gameId, perspective }
}

function retentionKeysEqual(
  a: MapDisplayRetentionKey | null,
  b: MapDisplayRetentionKey | null
): boolean {
  return a?.gameId === b?.gameId && a?.perspective === b?.perspective
}

/**
 * Retains the last displayable combined map while map queries reload.
 * Clears synchronously when game id or perspective changes; retains across turn steps.
 */
export function useRetainedMapDisplay({
  combined,
  gameId,
  perspective,
  viewMode,
}: UseRetainedMapDisplayInput): UseRetainedMapDisplayResult {
  const retainedMapDataRef = useRef<CombinedMapData | null>(null)
  const retentionKeyRef = useRef<MapDisplayRetentionKey | null>(null)

  const currentKey = mapDisplayRetentionKey(gameId, perspective)
  if (!retentionKeysEqual(currentKey, retentionKeyRef.current)) {
    retainedMapDataRef.current = null
    retentionKeyRef.current = currentKey
  }

  if (combined != null && hasDisplayableMapData(combined)) {
    retainedMapDataRef.current = combined
  }

  const showingLiveCombined =
    combined != null && hasDisplayableMapData(combined)
  const displayMapData: CombinedMapData | null = showingLiveCombined
    ? combined
    : retainedMapDataRef.current
  const retainDuringLoad = shouldRetainMapDuringLoad(
    viewMode,
    showingLiveCombined ? null : retainedMapDataRef.current
  )

  return { displayMapData, retainDuringLoad }
}
