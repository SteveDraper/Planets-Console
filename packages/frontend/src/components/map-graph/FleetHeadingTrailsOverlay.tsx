/**
 * Screen-space fleet heading trails. Paint only -- no hit targets.
 */

import { useStore } from '@xyflow/react'
import {
  FLEET_HEADING_TRAIL_HYPERJUMP_DASHARRAY,
  FLEET_HEADING_TRAIL_STROKE_WIDTH_PX,
  type FleetHeadingTrail,
} from '../../analytics/fleet/fleetHeadingTrails'
import { usePlayerColor } from '../../stores/playerColors'
import { flowCenterFromMapNode, safeZoomScale } from './geometry'
import { useOverlayPaneSize } from './useOverlayPaneSize'

type FleetHeadingTrailsOverlayProps = {
  trails: readonly FleetHeadingTrail[]
}

export function FleetHeadingTrailsOverlay({ trails }: FleetHeadingTrailsOverlayProps) {
  const domNode = useStore((s) => s.domNode ?? null)
  const transform = useStore((s) => s.transform)
  const { width, height } = useOverlayPaneSize(domNode)

  if (!transform || width <= 0 || height <= 0 || trails.length === 0) {
    return null
  }

  const [tx, ty, rawScale] = transform
  const scale = safeZoomScale(rawScale)

  return (
    <div className="pointer-events-none absolute inset-0 z-[7]">
      <svg
        className="h-full w-full"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        aria-hidden
      >
        {trails.map((trail) => (
          <FleetHeadingTrailStroke
            key={trail.key}
            trail={trail}
            tx={tx}
            ty={ty}
            scale={scale}
          />
        ))}
      </svg>
    </div>
  )
}

function FleetHeadingTrailStroke({
  trail,
  tx,
  ty,
  scale,
}: {
  trail: FleetHeadingTrail
  tx: number
  ty: number
  scale: number
}) {
  const color = usePlayerColor(trail.playerId)
  const start = flowCenterFromMapNode({ x: trail.x, y: trail.y })
  const end = flowCenterFromMapNode({ x: trail.endX, y: trail.endY })
  const x1 = start.cx * scale + tx
  const y1 = start.cy * scale + ty
  const x2 = end.cx * scale + tx
  const y2 = end.cy * scale + ty

  return (
    <line
      x1={x1}
      y1={y1}
      x2={x2}
      y2={y2}
      stroke={color}
      strokeWidth={FLEET_HEADING_TRAIL_STROKE_WIDTH_PX}
      strokeLinecap="round"
      strokeDasharray={trail.isHyperjump ? FLEET_HEADING_TRAIL_HYPERJUMP_DASHARRAY : undefined}
      opacity={trail.opacity}
    />
  )
}
