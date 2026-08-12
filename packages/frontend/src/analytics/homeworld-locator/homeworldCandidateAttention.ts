/**
 * Panel candidate click → shared map attention request (pulse / conditional pan).
 */

import { requestMapAttention } from '../../stores/mapAttentionRequest'

/**
 * Request map pulse / conditional pan for a candidate planet.
 * Pan and pulse lifetime are owned by ``MapAttentionOrchestrator``.
 */
export function selectHomeworldCandidateForMapAttention(planetId: number): void {
  requestMapAttention({
    kind: 'homeworld-planet',
    planetId,
  })
}
