/**
 * Panel candidate click → assert-focus selection + shared map attention request.
 */

import { requestMapAttention } from '../../stores/mapAttentionRequest'
import { useHomeworldLocatorSelectionStore } from '../../stores/homeworldLocatorSelection'

/**
 * Select a candidate planet for assert-focus and request map pulse / conditional pan.
 * Pan and pulse lifetime are owned by ``MapAttentionOrchestrator``.
 */
export function selectHomeworldCandidateForMapAttention(planetId: number): void {
  useHomeworldLocatorSelectionStore.getState().setSelection({ kind: 'planet', planetId })
  requestMapAttention({
    kind: 'homeworld-planet',
    planetId,
  })
}
