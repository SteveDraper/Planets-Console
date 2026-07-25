import { useEffect, useState } from 'react'
import { useStore } from '@xyflow/react'
import { CONFIDENCE_DEFINITE } from '../../analytics/homeworld-locator/constants'
import type { HomeworldMapMarkerDisplay } from '../../analytics/homeworld-locator/mapAnalytic'
import { flowCenterFromMapNode, safeZoomScale } from './geometry'

/** Outer ring diameter in screen pixels (independent of zoom). */
const MARKER_DIAMETER_PX = 12

const DEFINITE_STROKE = '#f8fafc'
const POSSIBLE_STROKE = '#94a3b8'

/**
 * Homeworld locator planet decorations on the base map.
 * Solid ring = definite; dashed/lighter ring = possible.
 */
export function HomeworldMarkersOverlay({
  markers,
}: {
  markers: readonly HomeworldMapMarkerDisplay[]
}) {
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
  if (markers.length === 0) return null

  const [tx, ty, rawScale] = transform
  const scale = safeZoomScale(rawScale)
  const { width, height } = size
  const r = MARKER_DIAMETER_PX / 2

  return (
    <div className="pointer-events-none absolute inset-0 z-[6]" aria-hidden>
      <svg className="h-full w-full" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        {markers.map((marker) => {
          const { cx, cy } = flowCenterFromMapNode({ x: marker.x, y: marker.y })
          const paneX = cx * scale + tx
          const paneY = cy * scale + ty
          const definite = marker.confidenceTier === CONFIDENCE_DEFINITE
          return (
            <circle
              key={`hw-${marker.planetId}-${marker.perspective ?? 'o'}-${marker.confidenceTier}`}
              cx={paneX}
              cy={paneY}
              r={r}
              fill="none"
              stroke={definite ? DEFINITE_STROKE : POSSIBLE_STROKE}
              strokeWidth={definite ? 1.75 : 1.25}
              strokeDasharray={definite ? undefined : '3 2'}
              opacity={definite ? 1 : 0.75}
            />
          )
        })}
      </svg>
    </div>
  )
}
