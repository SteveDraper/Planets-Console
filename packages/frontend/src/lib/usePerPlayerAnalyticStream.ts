import { useCallback, useEffect, useRef, useState } from 'react'
import type { AnalyticShellScope } from '../api/bff'
import { analyticScopeKey } from './analyticScopeKey'
import type { AnalyticTableStreamConnectResult } from './analyticTableStreamConnect'
import {
  computeFreezeStreamHold,
  freezeStreamHoldKey,
  hasPendingPlayersForStream,
  streamSubscriptionPlayerIds,
} from './computeFreezeStreamHold'
import { errorDetailFromUnknown } from './queryRetry'
import { playerIdsFromStableKey } from './stablePlayerIdsKey'
import {
  type ClientStreamLifecycle,
  useComputeDiagnosticsStore,
} from '../stores/computeDiagnostics'

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
    streamFailureEvent: (playerId: number, summary: string) => TEvent
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
    incompleteExhaustedMessage: string
  }

export type UsePerPlayerAnalyticStreamOptions<
  TEvent extends StreamErrorEvent,
  TRefState,
  TPublished,
> = {
  /**
   * Stable id for this analytic's table stream (e.g. ``fleet``, ``scores``).
   * Prefixed onto ``connectionKey`` so diagnostics lifecycle rows do not collide
   * when multiple analytics share the same shell and player set.
   */
  streamId: string
  scope: AnalyticShellScope | null
  enabled: boolean
  playerIdsKey: string
  policy: PerPlayerAnalyticStreamPolicy<TEvent, TRefState, TPublished>
}

export type UsePerPlayerAnalyticStreamResult<TPublished> = {
  publishedByPlayerId: Map<number, TPublished>
}

export function recordClientStreamLifecycle(entry: ClientStreamLifecycle): void {
  const { enabled, upsertClientStream } = useComputeDiagnosticsStore.getState()
  if (!enabled) {
    return
  }
  upsertClientStream(entry)
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
  const { streamId, scope, enabled, playerIdsKey, policy } = options

  const diagnosticsEnabled = useComputeDiagnosticsStore((state) => state.enabled)
  const freezeStatus = useComputeDiagnosticsStore((state) => state.freezeStatus)
  const freezeHold =
    scope != null
      ? computeFreezeStreamHold(scope, {
          enabled: diagnosticsEnabled,
          freezeStatus,
        })
      : { holding: false, expectedPlayerIds: null }
  const freezeHoldKey = freezeStreamHoldKey(freezeHold)

  const scopeKey = scope != null ? analyticScopeKey(scope) : null
  const effectivePlayerIdsKey = enabled && playerIdsKey.length > 0 ? playerIdsKey : ''
  const connectionKey =
    enabled && scopeKey != null && effectivePlayerIdsKey.length > 0
      ? freezeHoldKey.length > 0
        ? `${streamId}:${scopeKey}:${effectivePlayerIdsKey}:${freezeHoldKey}`
        : `${streamId}:${scopeKey}:${effectivePlayerIdsKey}`
      : null

  const [publishedByPlayerId, setPublishedByPlayerId] = useState<Map<number, TPublished>>(
    new Map()
  )
  const refStateByPlayerId = useRef<Map<number, TRefState>>(new Map())
  const connectionKeyRef = useRef<string | null>(null)
  const streamGenerationRef = useRef(0)
  const scopeRef = useRef(scope)
  scopeRef.current = scope
  const freezeHoldRef = useRef(freezeHold)
  freezeHoldRef.current = freezeHold
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
  const applyStreamEventRef = useRef(applyStreamEvent)
  applyStreamEventRef.current = applyStreamEvent

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
    const playerIds = playerIdsFromStableKey(effectivePlayerIdsKey)
    const hold = freezeHoldRef.current
    const subscribedPlayerIds = streamSubscriptionPlayerIds(playerIds, hold)

    if (isNewConnection) {
      streamGenerationRef.current += 1
      recordClientStreamLifecycle({
        streamId,
        connectionKey,
        generation: streamGenerationRef.current,
        lastEventAt: null,
        lastEventType: null,
        lastConnectResult: null,
      })
    }

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

    const markIncompleteFailed = (summary: string, targetPlayerIds: number[]) => {
      for (const playerId of targetPlayerIds) {
        const state = refStateByPlayerId.current.get(playerId)
        if (state != null && activePolicy.isRefStateComplete(state)) {
          continue
        }
        applyStreamEventRef.current(
          playerId,
          activePolicy.streamFailureEvent(playerId, summary)
        )
      }
    }

    // Freeze + empty allowlist: server narrows to no subscriptions; keep rows pending.
    if (hold.holding && subscribedPlayerIds.length === 0) {
      recordClientStreamLifecycle({
        streamId,
        connectionKey,
        generation: streamGenerationRef.current,
        lastEventAt: new Date().toISOString(),
        lastEventType: null,
        lastConnectResult: 'freeze_held',
      })
      return () => {
        controller.abort()
        streamAbortControllerRef.current = null
        policyRef.current.onConnectionTeardown?.()
      }
    }

    void activePolicy
      .connectUntilComplete(activeScope, subscribedPlayerIds, {
        signal: controller.signal,
        onEvent: (event) => {
          recordClientStreamLifecycle({
            streamId,
            connectionKey,
            generation: streamGenerationRef.current,
            lastEventAt: new Date().toISOString(),
            lastEventType: event.type,
            lastConnectResult: null,
          })
          handleStreamEventRef.current(event)
        },
        hasPending: () =>
          hasPendingPlayersForStream(
            playerIds,
            (playerId) => {
              const state = refStateByPlayerId.current.get(playerId)
              return state != null && activePolicy.isRefStateComplete(state)
            },
            freezeHoldRef.current
          ),
      })
      .then((result) => {
        if (controller.signal.aborted) {
          return
        }
        recordClientStreamLifecycle({
          streamId,
          connectionKey,
          generation: streamGenerationRef.current,
          lastEventAt: new Date().toISOString(),
          lastEventType: null,
          lastConnectResult: result,
        })
        if (result === 'incomplete_exhausted') {
          // Only subscribed players can fail; held-out rows stay pending.
          markIncompleteFailed(
            activePolicy.incompleteExhaustedMessage,
            subscribedPlayerIds
          )
        }
      })
      .catch((error) => {
        if (controller.signal.aborted) {
          return
        }
        const summary = errorDetailFromUnknown(error)
        recordClientStreamLifecycle({
          streamId,
          connectionKey,
          generation: streamGenerationRef.current,
          lastEventAt: new Date().toISOString(),
          lastEventType: 'error',
          lastConnectResult: summary,
        })
        markIncompleteFailed(summary, subscribedPlayerIds)
      })

    return () => {
      controller.abort()
      streamAbortControllerRef.current = null
      policyRef.current.onConnectionTeardown?.()
    }
  }, [connectionKey, effectivePlayerIdsKey, streamId])

  return { publishedByPlayerId }
}
