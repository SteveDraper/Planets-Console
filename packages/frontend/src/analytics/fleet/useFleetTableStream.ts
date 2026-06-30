import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import type { FleetTableStreamEvent } from '../../api/fleetTableStreamEventSchema'
import { analyticScopeKey } from '../../lib/analyticScopeKey'
import { errorDetailFromUnknown } from '../../lib/queryRetry'
import {
  playerIdsFromStableKey,
  stablePlayerIdsKey,
} from '../scores/inferenceRowStreamState'
import { connectFleetTableStreamUntilComplete } from './fleetTableStreamConnect'
import {
  fleetPlayerStreamSliceFromState,
  initialFleetPlayerStreamState,
  reduceFleetPlayerStreamState,
  type FleetPlayerStreamSlice,
  type FleetPlayerStreamState,
} from './fleetTablePlayerStreamState'
import { useOrderedFleetPlayers } from './useOrderedFleetPlayers'

export type UseFleetTableStreamResult = {
  streamPlayersById: Map<number, FleetPlayerStreamSlice>
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

  const scopeKey = scope != null ? analyticScopeKey(scope) : null
  const connectionKey =
    enabled && scopeKey != null && playerIdsKey.length > 0 ? `${scopeKey}:${playerIdsKey}` : null

  const [streamPlayersById, setStreamPlayersById] = useState<Map<number, FleetPlayerStreamSlice>>(
    new Map()
  )
  const playerStreamStateRef = useRef<Map<number, FleetPlayerStreamState>>(new Map())
  const connectionKeyRef = useRef<string | null>(null)
  const scopeRef = useRef(scope)
  scopeRef.current = scope
  const streamAbortControllerRef = useRef<AbortController | null>(null)

  const publishPlayerState = useCallback((playerId: number) => {
    const state = playerStreamStateRef.current.get(playerId)
    if (state == null) {
      return
    }
    const slice = fleetPlayerStreamSliceFromState(state)
    setStreamPlayersById((previous) => {
      const next = new Map(previous)
      if (slice == null) {
        next.delete(playerId)
      } else {
        next.set(playerId, slice)
      }
      return next
    })
  }, [])

  const applyStreamEvent = useCallback(
    (playerId: number, event: FleetTableStreamEvent) => {
      const current = playerStreamStateRef.current.get(playerId) ?? initialFleetPlayerStreamState()
      const next = reduceFleetPlayerStreamState(current, event)
      playerStreamStateRef.current.set(playerId, next)
      publishPlayerState(playerId)
    },
    [publishPlayerState]
  )

  const handleStreamEvent = useCallback(
    (event: FleetTableStreamEvent) => {
      if (event.type === 'error' && event.playerId == null) {
        for (const playerId of playerStreamStateRef.current.keys()) {
          applyStreamEvent(playerId, { ...event, playerId })
        }
        return
      }
      const playerId = 'playerId' in event ? event.playerId : undefined
      if (typeof playerId !== 'number') {
        return
      }
      applyStreamEvent(playerId, event)
    },
    [applyStreamEvent]
  )
  const handleStreamEventRef = useRef(handleStreamEvent)
  handleStreamEventRef.current = handleStreamEvent

  useEffect(() => {
    if (connectionKey == null) {
      connectionKeyRef.current = null
      setStreamPlayersById(new Map())
      playerStreamStateRef.current = new Map()
      return
    }

    const activeScope = scopeRef.current
    if (activeScope == null) {
      return
    }

    const isNewConnection = connectionKeyRef.current !== connectionKey
    connectionKeyRef.current = connectionKey
    const playerIds = playerIdsFromStableKey(playerIdsKey)

    streamAbortControllerRef.current?.abort()

    if (isNewConnection) {
      const initialStates = new Map<number, FleetPlayerStreamState>()
      for (const playerId of playerIds) {
        initialStates.set(playerId, initialFleetPlayerStreamState())
      }
      playerStreamStateRef.current = initialStates
      setStreamPlayersById(new Map())
    }

    const controller = new AbortController()
    streamAbortControllerRef.current = controller

    const markIncompletePlayersFailed = (summary: string) => {
      setStreamPlayersById((previous) => {
        const next = new Map(previous)
        for (const playerId of playerIds) {
          const current = next.get(playerId)
          if (current?.isComplete) {
            continue
          }
          next.set(playerId, {
            isComplete: true,
            isFinal: false,
            summary,
            error: summary,
          })
        }
        return next
      })
    }

    void connectFleetTableStreamUntilComplete(activeScope, playerIds, {
      signal: controller.signal,
      onEvent: (event) => handleStreamEventRef.current(event),
      hasPendingPlayers: () => {
        for (const playerId of playerIds) {
          const state = playerStreamStateRef.current.get(playerId)
          if (state == null || !state.isComplete) {
            return true
          }
        }
        return false
      },
    })
      .then((result) => {
        if (controller.signal.aborted) {
          return
        }
        if (result === 'conflict_exhausted') {
          markIncompletePlayersFailed(
            'Fleet table stream could not reconnect for this scope.'
          )
          return
        }
        if (result === 'incomplete_exhausted') {
          markIncompletePlayersFailed(
            'Fleet table stream ended before all visible players completed.'
          )
        }
      })
      .catch((error) => {
        if (controller.signal.aborted) {
          return
        }
        const summary = errorDetailFromUnknown(error)
        markIncompletePlayersFailed(summary)
      })

    return () => {
      controller.abort()
      streamAbortControllerRef.current = null
    }
  }, [connectionKey, playerIdsKey])

  return { streamPlayersById }
}
