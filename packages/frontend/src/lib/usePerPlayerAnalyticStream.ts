import { useCallback, useEffect, useRef, useState } from 'react'
import type { AnalyticShellScope } from '../api/bff'
import { analyticScopeKey } from './analyticScopeKey'
import type { AnalyticTableStreamConnectResult } from './analyticTableStreamConnect'
import { errorDetailFromUnknown } from './queryRetry'

function playerIdsFromStableKey(playerIdsKey: string): number[] {
  if (playerIdsKey.length === 0) {
    return []
  }
  return playerIdsKey.split(',').map((part) => Number(part))
}

type StreamErrorEvent = {
  type: string
  playerId?: number | null
}

export type PerPlayerStreamEventRouterContext<TEvent> = {
  applyToPlayer: (playerId: number, event: TEvent) => void
  applyToAllPlayers: (event: TEvent) => void
}

export type PerPlayerAnalyticStreamPolicy<TEvent extends StreamErrorEvent, TRefState, TPublished> =
  {
    initialRefState: (playerId: number) => TRefState
    reduceRefState: (current: TRefState, event: TEvent, playerId: number) => TRefState
    isRefStateComplete: (state: TRefState) => boolean
    publishedFromRefState: (playerId: number, state: TRefState) => TPublished | null
    seedPublishedOnNewConnection?: (playerIds: number[]) => Map<number, TPublished>
    markIncompleteFailed: (
      playerIds: number[],
      previous: Map<number, TPublished>,
      summary: string
    ) => Map<number, TPublished>
    routeStreamEvent?: (
      event: TEvent,
      context: PerPlayerStreamEventRouterContext<TEvent>
    ) => boolean
    onConnectionCleared?: () => void
    onConnectionTeardown?: () => void
    connectUntilComplete: (
      scope: AnalyticShellScope,
      playerIds: number[],
      handlers: {
        signal: AbortSignal
        onEvent: (event: TEvent) => void
        hasPending: () => boolean
      }
    ) => Promise<AnalyticTableStreamConnectResult>
    conflictExhaustedMessage: string
    incompleteExhaustedMessage: string
  }

export type UsePerPlayerAnalyticStreamOptions<
  TEvent extends StreamErrorEvent,
  TRefState,
  TPublished,
> = {
  scope: AnalyticShellScope | null
  enabled: boolean
  playerIdsKey: string
  policy: PerPlayerAnalyticStreamPolicy<TEvent, TRefState, TPublished>
}

export type UsePerPlayerAnalyticStreamResult<TPublished> = {
  publishedByPlayerId: Map<number, TPublished>
}

function defaultRouteStreamEvent<TEvent extends StreamErrorEvent>(
  event: TEvent,
  context: PerPlayerStreamEventRouterContext<TEvent>,
  playerIdsInRef: Iterable<number>
): void {
  if (event.type === 'error' && event.playerId == null) {
    for (const playerId of playerIdsInRef) {
      context.applyToPlayer(playerId, { ...event, playerId } as TEvent)
    }
    return
  }
  const playerId = 'playerId' in event ? event.playerId : undefined
  if (typeof playerId === 'number') {
    context.applyToPlayer(playerId, event)
  }
}

export function usePerPlayerAnalyticStream<
  TEvent extends StreamErrorEvent,
  TRefState,
  TPublished,
>(
  options: UsePerPlayerAnalyticStreamOptions<TEvent, TRefState, TPublished>
): UsePerPlayerAnalyticStreamResult<TPublished> {
  const { scope, enabled, playerIdsKey, policy } = options

  const scopeKey = scope != null ? analyticScopeKey(scope) : null
  const connectionKey =
    enabled && scopeKey != null && playerIdsKey.length > 0 ? `${scopeKey}:${playerIdsKey}` : null

  const [publishedByPlayerId, setPublishedByPlayerId] = useState<Map<number, TPublished>>(
    new Map()
  )
  const refStateByPlayerId = useRef<Map<number, TRefState>>(new Map())
  const connectionKeyRef = useRef<string | null>(null)
  const scopeRef = useRef(scope)
  scopeRef.current = scope
  const streamAbortControllerRef = useRef<AbortController | null>(null)
  const policyRef = useRef(policy)
  policyRef.current = policy

  const publishPlayerState = useCallback((playerId: number) => {
    const activePolicy = policyRef.current
    const state = refStateByPlayerId.current.get(playerId)
    if (state == null) {
      return
    }
    const published = activePolicy.publishedFromRefState(playerId, state)
    setPublishedByPlayerId((previous) => {
      const next = new Map(previous)
      if (published == null) {
        next.delete(playerId)
      } else {
        next.set(playerId, published)
      }
      return next
    })
  }, [])

  const applyStreamEvent = useCallback(
    (playerId: number, event: TEvent) => {
      const activePolicy = policyRef.current
      const current =
        refStateByPlayerId.current.get(playerId) ?? activePolicy.initialRefState(playerId)
      const next = activePolicy.reduceRefState(current, event, playerId)
      refStateByPlayerId.current.set(playerId, next)
      publishPlayerState(playerId)
    },
    [publishPlayerState]
  )

  const handleStreamEvent = useCallback(
    (event: TEvent) => {
      const activePolicy = policyRef.current
      const routerContext: PerPlayerStreamEventRouterContext<TEvent> = {
        applyToPlayer: applyStreamEvent,
        applyToAllPlayers: (fanOutEvent) => {
          for (const playerId of refStateByPlayerId.current.keys()) {
            applyStreamEvent(playerId, fanOutEvent)
          }
        },
      }
      if (activePolicy.routeStreamEvent?.(event, routerContext)) {
        return
      }
      defaultRouteStreamEvent(event, routerContext, refStateByPlayerId.current.keys())
    },
    [applyStreamEvent]
  )
  const handleStreamEventRef = useRef(handleStreamEvent)
  handleStreamEventRef.current = handleStreamEvent

  useEffect(() => {
    const activePolicy = policyRef.current

    if (connectionKey == null) {
      connectionKeyRef.current = null
      setPublishedByPlayerId(new Map())
      refStateByPlayerId.current = new Map()
      activePolicy.onConnectionCleared?.()
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
      const initialStates = new Map<number, TRefState>()
      for (const playerId of playerIds) {
        initialStates.set(playerId, activePolicy.initialRefState(playerId))
      }
      refStateByPlayerId.current = initialStates

      const seeded = activePolicy.seedPublishedOnNewConnection?.(playerIds)
      setPublishedByPlayerId(seeded ?? new Map())
    }

    const controller = new AbortController()
    streamAbortControllerRef.current = controller

    const markIncompleteFailed = (summary: string) => {
      setPublishedByPlayerId((previous) =>
        activePolicy.markIncompleteFailed(playerIds, previous, summary)
      )
    }

    void activePolicy
      .connectUntilComplete(activeScope, playerIds, {
        signal: controller.signal,
        onEvent: (event) => handleStreamEventRef.current(event),
        hasPending: () => {
          for (const playerId of playerIds) {
            const state = refStateByPlayerId.current.get(playerId)
            if (state == null || !activePolicy.isRefStateComplete(state)) {
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
          markIncompleteFailed(activePolicy.conflictExhaustedMessage)
          return
        }
        if (result === 'incomplete_exhausted') {
          markIncompleteFailed(activePolicy.incompleteExhaustedMessage)
        }
      })
      .catch((error) => {
        if (controller.signal.aborted) {
          return
        }
        markIncompleteFailed(errorDetailFromUnknown(error))
      })

    return () => {
      controller.abort()
      streamAbortControllerRef.current = null
      policyRef.current.onConnectionTeardown?.()
    }
  }, [connectionKey, playerIdsKey])

  return { publishedByPlayerId }
}
