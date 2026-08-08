/**
 * **Map interaction surface** (ADR 0012): pane pointer owner, contributor
 * registry, async sample slot, **map hover composition policy**, and hover chrome.
 *
 * Must mount under ``ReactFlow``. Paint **map layer**s stay pointer-event transparent.
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useStore } from '@xyflow/react'
import { composeMapHoverContributions } from './mapHoverCompositionPolicy'
import { createAsyncSampleSlot } from './mapHoverAsyncSlot'
import type { MapHoverSyncBlock } from './mapHoverContributionTypes'
import { MapHoverChrome } from './MapHoverChrome'
import {
  MapInteractionRegistryProvider,
  mapHitContextFromState,
  useMapInteractionHitState,
  useMapInteractionRegistry,
  type MapInteractionHitState,
} from './mapInteractionRegistry'
import {
  applyReadyAsyncBlocks,
  findPendingAsyncHover,
  omitPendingAsyncContributions,
} from './resolveMapHoverAsync'
import { useMapPanePointer } from './useMapPanePointer'

type MapInteractionSurfaceProps = {
  children: ReactNode
}

function MapInteractionHoverEngine() {
  const { list, version } = useMapInteractionRegistry()
  const hitState = useMapInteractionHitState()
  const [asyncReady, setAsyncReady] = useState<{
    requestKey: string
    hitEpoch: number
    blocks: readonly MapHoverSyncBlock[]
  } | null>(null)
  const slotRef = useRef(createAsyncSampleSlot<readonly MapHoverSyncBlock[]>())

  const hit = mapHitContextFromState(hitState)
  // ``version`` bumps on register/unregister; ``list`` identity is stable.
  const contributors = list()

  const rawContributions = useMemo(() => {
    const out = []
    for (const contributor of contributors) {
      if (hit != null) {
        const contribution = contributor.hitTest(hit)
        if (contribution != null) out.push(contribution)
        continue
      }
      // Pinned planet labels persist after the pointer leaves the pane.
      if (
        contributor.role === 'planet' &&
        hitState.domNode != null &&
        hitState.transform != null
      ) {
        const sticky = contributor.hitTest({
          clientPos: { x: 0, y: 0 },
          hitEpoch: 0,
          domNode: hitState.domNode,
          transform: hitState.transform,
        })
        if (
          sticky?.placement.mode === 'anchor' &&
          sticky.placement.pinned === true
        ) {
          out.push(sticky)
        }
      }
    }
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps -- ``version`` invalidates ``contributors``
  }, [contributors, hit, hitState.domNode, hitState.transform, version])

  const scheduledKeyRef = useRef<string | null>(null)

  useEffect(() => {
    if (hitState.clientPos == null) {
      slotRef.current.cancel()
      scheduledKeyRef.current = null
      return
    }
    if (hit == null) return

    const pending = findPendingAsyncHover(rawContributions, contributors)
    if (pending == null) return

    const request = {
      hitEpoch: hit.hitEpoch,
      requestKey: pending.requestKey,
    }
    const scheduleKey = `${request.hitEpoch}:${request.requestKey}`
    if (scheduledKeyRef.current === scheduleKey) return
    scheduledKeyRef.current = scheduleKey

    let cancelled = false
    void slotRef.current
      .schedule(request, () => pending.contributor.fetch!(hit))
      .then((result) => {
        if (cancelled) return
        if (result.status === 'ready') {
          setAsyncReady({
            requestKey: result.request.requestKey,
            hitEpoch: result.request.hitEpoch,
            blocks: result.value,
          })
        } else if (result.status === 'error') {
          setAsyncReady({
            requestKey: request.requestKey,
            hitEpoch: request.hitEpoch,
            blocks: [],
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [hit, hitState.clientPos, hitState.hitEpoch, rawContributions, contributors])

  const resolved = useMemo(() => {
    if (hit == null) {
      return omitPendingAsyncContributions(rawContributions)
    }
    let next = rawContributions
    if (
      asyncReady != null &&
      asyncReady.hitEpoch === hit.hitEpoch &&
      rawContributions.some((c) =>
        c.blocks.some(
          (b) =>
            b.type === 'async' &&
            b.status === 'pending' &&
            b.requestKey === asyncReady.requestKey
        )
      )
    ) {
      next = applyReadyAsyncBlocks(
        next,
        asyncReady.requestKey,
        asyncReady.blocks
      )
    }
    return omitPendingAsyncContributions(next)
  }, [rawContributions, asyncReady, hit])

  const composition = useMemo(
    () => composeMapHoverContributions(resolved),
    [resolved]
  )

  return (
    <MapHoverChrome composition={composition} clientPos={hitState.clientPos} />
  )
}

export function MapInteractionSurface({ children }: MapInteractionSurfaceProps) {
  const { clientPos, domNode, hitEpoch } = useMapPanePointer()
  const transform = useStore((s) => s.transform)

  const hit: MapInteractionHitState = useMemo(
    () => ({
      clientPos,
      hitEpoch,
      domNode,
      transform,
    }),
    [clientPos, hitEpoch, domNode, transform]
  )

  return (
    <MapInteractionRegistryProvider hit={hit}>
      {children}
      <MapInteractionHoverEngine />
    </MapInteractionRegistryProvider>
  )
}
