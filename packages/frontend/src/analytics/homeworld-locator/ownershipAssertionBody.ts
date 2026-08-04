/**
 * Wire body for ownership homeworld assertions (panel + map menu).
 */

import type { HomeworldAssertionRequest } from './api'
import type { OwnershipAssertTarget } from './resolveOwnershipAssertTarget'

type OwnershipAction = 'upsert' | 'revoke'

export function buildOwnershipAssertionBody(
  action: OwnershipAction,
  ownerSlot: number,
  target: OwnershipAssertTarget
): HomeworldAssertionRequest {
  return {
    axis: 'ownership',
    action,
    ownerSlot,
    planetId: target.keying === 'planet' ? target.planetId : (target.planetId ?? null),
    sectorIndex: target.keying === 'sector' ? target.sectorIndex : null,
  }
}
