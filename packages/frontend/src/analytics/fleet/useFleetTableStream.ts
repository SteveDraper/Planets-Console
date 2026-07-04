import { useMemo } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import type { FleetTableStreamEvent } from '../../api/fleetTableStreamEventSchema'
import {
  usePerPlayerAnalyticStream,
  type PerPlayerAnalyticStreamPolicy,
} from '../../lib/usePerPlayerAnalyticStream'
import { stablePlayerIdsKey } from '../../lib/stablePlayerIdsKey'
import { connectFleetTableStreamUntilComplete } from './fleetTableStreamConnect'
import {
  fleetPlayerStreamSliceFromState,
  initialFleetPlayerStreamState,
  pendingFleetPlayerStreamSlice,
  reduceFleetPlayerStreamState,
  type FleetPlayerStreamSlice,
  type FleetPlayerStreamState,
} from './fleetTablePlayerStreamState'
import { useOrderedFleetPlayers } from './useOrderedFleetPlayers'

export type UseFleetTableStreamResult = {
  streamPlayersById: Map<number, FleetPlayerStreamSlice>
}

const fleetTableStreamPolicy: PerPlayerAnalyticStreamPolicy<
  FleetTableStreamEvent,
  FleetPlayerStreamState,
  FleetPlayerStreamSlice
> = {
  initialRefState: () => initialFleetPlayerStreamState(),
  reduceRefState: (current, event) => reduceFleetPlayerStreamState(current, event),
  isRefStateComplete: (state) => state.isComplete,
  publishedFromRefState: (_playerId, state) => fleetPlayerStreamSliceFromState(state),
  seedPublishedOnNewConnection: (playerIds) => {
    const initialSlices = new Map<number, FleetPlayerStreamSlice>()
    for (const playerId of playerIds) {
      initialSlices.set(playerId, pendingFleetPlayerStreamSlice())
    }
    return initialSlices
  },
  streamFailureEvent: (playerId, summary) => ({
    type: 'error',
    playerId,
    detail: summary,
  }),
  connectUntilComplete: (scope, playerIds, handlers) =>
    connectFleetTableStreamUntilComplete(scope, playerIds, {
      signal: handlers.signal,
      onEvent: handlers.onEvent,
      hasPendingPlayers: handlers.hasPending,
    }),
  conflictExhaustedMessage: 'Fleet table stream could not reconnect for this scope.',
  incompleteExhaustedMessage:
    'Fleet table stream ended before all visible players completed.',
}

export function useFleetTableStream(
  scope: AnalyticShellScope | null,
  enabled: boolean
): UseFleetTableStreamResult {
  const { players: visiblePlayers } = useOrderedFleetPlayers({ visibleOnly: true })

  const playerIdsKey = useMemo(() => {
    if (!enabled || visiblePlayers.length === 0) {
      return ''
    }
    return stablePlayerIdsKey(visiblePlayers.map((player) => player.playerId))
  }, [enabled, visiblePlayers])

  const { publishedByPlayerId: streamPlayersById } = usePerPlayerAnalyticStream({
    scope,
    enabled,
    playerIdsKey,
    policy: fleetTableStreamPolicy,
  })

  return { streamPlayersById }
}
