import { useEffect, useState } from 'react'
import { useStore } from '@xyflow/react'
import type { CombinedMapData } from '../../api/bff'
import {
  buildWarpWellOverlayPaneLines,
  WARP_WELL_OVERLAY_ZOOM_THRESHOLD,
} from '../../lib/warpWellOverlay'
import { safeZoomScale } from './geometry'

/** Slightly warmer than the coordinate grid so both remain distinguishable. */
const WARP_WELL_STROKE = '#78716c'

export function NormalWarpWellOutlinesOverlay({ mapNodes }: { mapNodes: CombinedMapData['nodes'] }) {
  const domNode = useStore((s) => s.domNode ?? null)
  const transform = useStore((s) => s.transform)
  const [size, setSize] = useState({ width: 0, height: 0 })

  useEffect(() => {
    if (!domNode) return
    let raf = 0
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0]?.contentRect ?? { width: 0, height: 0 }
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => setSize({ width, height }))
    })
    ro.observe(domNode)
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
    }
  }, [domNode])

  if (!transform || size.width <= 0 || size.height <= 0) return null
  const [tx, ty, rawScale] = transform
  const scale = safeZoomScale(rawScale)
  if (scale < WARP_WELL_OVERLAY_ZOOM_THRESHOLD) return null

  const { width, height } = size
  const lines = buildWarpWellOverlayPaneLines(
    mapNodes,
    { width, height, tx, ty, scale },
    WARP_WELL_OVERLAY_ZOOM_THRESHOLD
  )

  if (lines.length === 0) return null

  return (
    <div className="pointer-events-none absolute inset-0 z-[5]" aria-hidden>
      <svg className="h-full w-full" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        <g stroke={WARP_WELL_STROKE} strokeWidth={1}>
          {lines.map(({ key, x1, y1, x2, y2 }) => (
            <line key={key} x1={x1} y1={y1} x2={x2} y2={y2} />
          ))}
        </g>
      </svg>
    </div>
  )
}
