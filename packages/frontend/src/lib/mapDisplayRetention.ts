import type { CombinedMapData } from '../api/bff'

/** Pure retention predicates; cross-turn ref retention lives in useRetainedMapDisplay. */

export function hasDisplayableMapData(data: CombinedMapData | null | undefined): boolean {
  return (data?.nodes.length ?? 0) > 0
}

/** Keep the map pane mounted (preserving React Flow viewport) while turn or map data reloads. */
export function shouldRetainMapDuringLoad(
  viewMode: 'tabular' | 'map',
  retainedMapData: CombinedMapData | null
): boolean {
  return viewMode === 'map' && hasDisplayableMapData(retainedMapData)
}
