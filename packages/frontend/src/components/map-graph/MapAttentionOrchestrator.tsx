/**
 * Inside React Flow: consume map attention bus, pan when ready, drive pulse lifetime.
 */

import { useEffect, useRef } from 'react'
import { useReactFlow, useStore } from '@xyflow/react'
import {
  mapAttentionPulseMs,
  resolveMapAttentionTarget,
  type HomeworldAttentionMarker,
} from '../../lib/mapAttention'
import { useMapAttentionRequestStore } from '../../stores/mapAttentionRequest'
import { recenterViewportOnFlowPoint } from './geometry'

export function MapAttentionOrchestrator({
  homeworldMarkers,
}: {
  homeworldMarkers: readonly HomeworldAttentionMarker[]
}) {
  const pending = useMapAttentionRequestStore((s) => s.pending)
  const clearAttention = useMapAttentionRequestStore((s) => s.clearAttention)
  const { getViewport, setViewport } = useReactFlow()
  const domNode = useStore((s) => s.domNode ?? null)
  const handledTokenRef = useRef<number | null>(null)

  useEffect(() => {
    if (pending == null) {
      handledTokenRef.current = null
      return
    }
    if (handledTokenRef.current === pending.token) return
    if (domNode == null) return

    const rect = domNode.getBoundingClientRect()
    const vp = getViewport()
    const resolved = resolveMapAttentionTarget(pending, {
      homeworldMarkers,
      viewport: {
        x: vp.x,
        y: vp.y,
        zoom: vp.zoom,
        width: rect.width,
        height: rect.height,
      },
    })
    if (resolved == null) return

    handledTokenRef.current = pending.token
    if (!resolved.needsPan) return
    recenterViewportOnFlowPoint(
      resolved.flowX,
      resolved.flowY,
      domNode,
      getViewport,
      setViewport
    )
  }, [pending, homeworldMarkers, domNode, getViewport, setViewport])

  useEffect(() => {
    if (pending == null) return
    const timer = setTimeout(
      () => clearAttention(),
      mapAttentionPulseMs(pending.kind)
    )
    return () => clearTimeout(timer)
  }, [pending, clearAttention])

  useEffect(() => {
    return () => {
      clearAttention()
    }
  }, [clearAttention])

  return null
}
