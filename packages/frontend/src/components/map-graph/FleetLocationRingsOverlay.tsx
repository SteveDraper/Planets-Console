/**
 * Screen-fixed fleet location rings paint. Descriptive hover is owned by the
 * **map interaction surface** (no pointer capture, no overlay tooltip).
 */

import { useStore } from '@xyflow/react'
import {
  fleetLocationRingPaintRadiusPx,
  fleetLocationRingStackKey,
  type FleetLocationRingStack,
} from '../../analytics/fleet/fleetLocationRings'
import { usePlayerColor } from '../../stores/playerColors'
import { flowCenterFromMapNode, safeZoomScale } from './geometry'
import { useOverlayPaneSize } from './useOverlayPaneSize'

type FleetLocationRingsOverlayProps = {
  stacks: readonly FleetLocationRingStack[]
}

export function FleetLocationRingsOverlay({ stacks }: FleetLocationRingsOverlayProps) {
  const domNode = useStore((s) => s.domNode ?? null)
  const transform = useStore((s) => s.transform)
  const { width, height } = useOverlayPaneSize(domNode)

  if (!transform || width <= 0 || height <= 0 || stacks.length === 0) {
    return null
  }

  const [tx, ty, rawScale] = transform
  const scale = safeZoomScale(rawScale)

  return (
    <div className="pointer-events-none absolute inset-0 z-[8]">
      <svg
        className="h-full w-full"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        aria-hidden
      >
        {stacks.map((stack) => {
          const { cx, cy } = flowCenterFromMapNode({ x: stack.x, y: stack.y })
          const paneX = cx * scale + tx
          const paneY = cy * scale + ty
          const paintRadius = fleetLocationRingPaintRadiusPx(stack.diameterPx, stack.strokeWidthPx)
          const circumference = 2 * Math.PI * paintRadius
          let dashOffset = 0
          return (
            <g key={stack.key} transform={`translate(${paneX} ${paneY})`}>
              <g transform="rotate(-90)" opacity={stack.opacity}>
                {stack.arcs.map((arc) => {
                  const dash = arc.share * circumference
                  const gap = Math.max(0, circumference - dash)
                  const offset = dashOffset
                  dashOffset += dash
                  return (
                    <FleetLocationRingArcStroke
                      key={arc.playerId}
                      playerId={arc.playerId}
                      paintRadius={paintRadius}
                      strokeWidthPx={stack.strokeWidthPx}
                      dash={dash}
                      gap={gap}
                      dashOffset={offset}
                    />
                  )
                })}
              </g>
            </g>
          )
        })}
      </svg>
    </div>
  )
}

/** Build the set of ``fleetLocationRingStackKey`` values for planet map nodes. */
export function planetCoordKeysFromMapNodes(
  mapNodes: readonly { x: number; y: number }[]
): Set<string> {
  const keys = new Set<string>()
  for (const node of mapNodes) {
    keys.add(fleetLocationRingStackKey(Number(node.x), Number(node.y)))
  }
  return keys
}

function FleetLocationRingArcStroke({
  playerId,
  paintRadius,
  strokeWidthPx,
  dash,
  gap,
  dashOffset,
}: {
  playerId: number
  paintRadius: number
  strokeWidthPx: number
  dash: number
  gap: number
  dashOffset: number
}) {
  const color = usePlayerColor(playerId)
  return (
    <circle
      cx={0}
      cy={0}
      r={paintRadius}
      fill="none"
      stroke={color}
      strokeWidth={strokeWidthPx}
      strokeDasharray={`${dash} ${gap}`}
      strokeDashoffset={-dashOffset}
      strokeLinecap="butt"
    />
  )
}
