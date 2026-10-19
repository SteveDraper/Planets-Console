import type { AnalyticShellScope } from '../../api/bff'
import { usePerPlayerAnalyticStream } from '../../lib/usePerPlayerAnalyticStream'
import { stablePlayerIdsKey } from '../../lib/stablePlayerIdsKey'
import type { FleetPlayerStreamSlice } from './fleetTablePlayerStreamState'
import { fleetTableStreamPolicy } from './useFleetTableStream'

const fleetHoverAdmissionStreamPolicy = {
  ...fleetTableStreamPolicy,
  incompleteExhaustedMessage:
    'Fleet emphasis stream ended before the hovered player completed.',
}

/**
 * Admit one visibility-off player for fleet location ring emphasis.
 * A separate connection so the fleet stream for players already on screen
 * is not aborted, reconnected, or blanked.
 */
export function useFleetHoverAdmissionStream(
  scope: AnalyticShellScope | null,
  playerId: number | null
): FleetPlayerStreamSlice | null {
  const playerIdsKey = playerId == null ? '' : stablePlayerIdsKey([playerId])
  const { publishedByPlayerId } = usePerPlayerAnalyticStream({
    streamId: 'fleet-location-ring-emphasis',
    scope,
    enabled: playerId != null,
    playerIdsKey,
    policy: fleetHoverAdmissionStreamPolicy,
  })
  if (playerId == null) {
    return null
  }
  return publishedByPlayerId.get(playerId) ?? null
}
