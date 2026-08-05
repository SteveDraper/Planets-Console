/**
 * Inside React Flow: on candidate flash request, pan only when off-screen (no zoom change).
 */

import { useEffect, useRef } from 'react'
import { useReactFlow, useStore } from '@xyflow/react'
import {
  resolveHomeworldCandidatePan,
  type HomeworldCandidateAttentionMarker,
} from '../../analytics/homeworld-locator/homeworldCandidateAttention'
import { HOMEWORLD_CANDIDATE_FLASH_MS } from '../../analytics/homeworld-locator/constants'
import { recenterViewportOnFlowPoint } from './geometry'
import { useHomeworldCandidateFlashStore } from '../../stores/homeworldCandidateFlash'

export function HomeworldCandidateAttentionController({
  markers,
}: {
  markers: readonly HomeworldCandidateAttentionMarker[]
}) {
  const flashTarget = useHomeworldCandidateFlashStore((s) => s.flashTarget)
  const clearFlash = useHomeworldCandidateFlashStore((s) => s.clearFlash)
  const { getViewport, setViewport } = useReactFlow()
  const domNode = useStore((s) => s.domNode ?? null)
  const handledTokenRef = useRef<number | null>(null)

  useEffect(() => {
    if (flashTarget == null) {
      handledTokenRef.current = null
      return
    }
    if (handledTokenRef.current === flashTarget.token) return
    // Wait for React Flow's domNode before consuming the token so a late pane
    // can still pan for this flash (re-run when domNode appears).
    if (domNode == null) return

    const rect = domNode.getBoundingClientRect()
    const vp = getViewport()
    const resolved = resolveHomeworldCandidatePan(flashTarget.planetId, markers, {
      x: vp.x,
      y: vp.y,
      zoom: vp.zoom,
      width: rect.width,
      height: rect.height,
    })
    // Wait for the marker before consuming the token so late-arriving markers
    // can still pan for this flash (re-run when markers populate).
    if (resolved == null) return

    handledTokenRef.current = flashTarget.token
    if (!resolved.needsPan) return
    recenterViewportOnFlowPoint(
      resolved.flowX,
      resolved.flowY,
      domNode,
      getViewport,
      setViewport
    )
  }, [flashTarget, markers, domNode, getViewport, setViewport])

  useEffect(() => {
    if (flashTarget == null) return
    const timer = setTimeout(() => clearFlash(), HOMEWORLD_CANDIDATE_FLASH_MS)
    return () => clearTimeout(timer)
  }, [flashTarget, clearFlash])

  useEffect(() => {
    return () => {
      clearFlash()
    }
  }, [clearFlash])

  return null
}
