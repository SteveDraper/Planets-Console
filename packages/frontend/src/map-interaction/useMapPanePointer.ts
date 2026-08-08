/**
 * Single pane pointer owner for the **map interaction surface**.
 *
 * Must be called from a component mounted under ``ReactFlow`` (xyflow store).
 * Paint **map layer**s stay pointer-event transparent; they must not attach
 * competing listeners for descriptive hover.
 */

import { useEffect, useState } from 'react'
import { useStore } from '@xyflow/react'

export type MapPaneClientPos = { x: number; y: number }

export type MapPanePointerState = {
  clientPos: MapPaneClientPos | null
  domNode: HTMLElement | null
  /**
   * Increments on each pane ``mousemove``; resets to 0 on leave.
   * Async sample slots discard results whose epoch no longer matches.
   */
  hitEpoch: number
}

/**
 * Tracks client pointer over the React Flow pane and a monotonic hit epoch.
 *
 * Prefer this over attaching per-overlay ``mousemove`` listeners for hover.
 */
export function useMapPanePointer(): MapPanePointerState {
  const domNode = useStore((s) => s.domNode ?? null)
  const [clientPos, setClientPos] = useState<MapPaneClientPos | null>(null)
  const [hitEpoch, setHitEpoch] = useState(0)

  useEffect(() => {
    const el = domNode
    if (!el) return

    const onMove = (e: MouseEvent) => {
      setClientPos({ x: e.clientX, y: e.clientY })
      setHitEpoch((n) => n + 1)
    }
    const onLeave = () => {
      setClientPos(null)
      setHitEpoch(0)
    }
    el.addEventListener('mousemove', onMove)
    el.addEventListener('mouseleave', onLeave)
    return () => {
      el.removeEventListener('mousemove', onMove)
      el.removeEventListener('mouseleave', onLeave)
    }
  }, [domNode])

  return { clientPos, domNode, hitEpoch }
}
