import { useMemo } from 'react'
import { useStore } from '@xyflow/react'
import {
  fleetLocationRingPaintRadiusPx,
  fleetLocationRingStackKey,
  type FleetLocationRingStack,
} from '../../analytics/fleet/fleetLocationRings'
import { findFleetLocationRingStackAtPanePoint } from '../../analytics/fleet/fleetLocationRingHitTest'
import { FleetLocationRingTooltipBody } from '../../analytics/fleet/FleetLocationRingTooltipBody'
import { usePlayerColor } from '../../stores/playerColors'
import { useMapPaneClientPos } from './RegionOverlayHoverPanel'
import { flowCenterFromMapNode, safeZoomScale } from './geometry'
import { useOverlayPaneSize } from './useOverlayPaneSize'

type FleetLocationRingsOverlayProps = {
  stacks: readonly FleetLocationRingStack[]
  /**
   * Map-cell keys (`x,y`) that have a planet node. When planet labels are on,
   * stacks at those cells are shown on the planet label instead of here.
   */
  planetCoordKeys: ReadonlySet<string>
  /** When false, stacks at planet cells still use this overlay's tooltip. */
  planetLabelsEnabled: boolean
}

/**
 * Screen-fixed fleet location rings from shared stacks.
 * Hover uses pane pointer hit-test (no pointer-events capture) so planet hover still works.
 */
export function FleetLocationRingsOverlay({
  stacks,
  planetCoordKeys,
  planetLabelsEnabled,
}: FleetLocationRingsOverlayProps) {
  const domNode = useStore((s) => s.domNode ?? null)
  const transform = useStore((s) => s.transform)
  const { width, height } = useOverlayPaneSize(domNode)
  const { clientPos } = useMapPaneClientPos()

  const hovered = useMemo(() => {
    if (
      clientPos == null ||
      domNode == null ||
      !transform ||
      stacks.length === 0
    ) {
      return null
    }
    const rect = domNode.getBoundingClientRect()
    const paneX = clientPos.x - rect.left
    const paneY = clientPos.y - rect.top
    return findFleetLocationRingStackAtPanePoint(stacks, paneX, paneY, transform)
  }, [clientPos, domNode, transform, stacks])

  const showStandaloneTooltip =
    hovered != null &&
    !(planetLabelsEnabled && planetCoordKeys.has(hovered.key))

  if (!transform || width <= 0 || height <= 0 || stacks.length === 0) {
    return null
  }

  const [tx, ty, rawScale] = transform
  const scale = safeZoomScale(rawScale)
  let hoveredPaneX = 0
  let hoveredPaneY = 0
  if (showStandaloneTooltip && hovered != null) {
    const { cx, cy } = flowCenterFromMapNode({ x: hovered.x, y: hovered.y })
    hoveredPaneX = cx * scale + tx
    hoveredPaneY = cy * scale + ty
  }

  return (
    <div className="pointer-events-none absolute inset-0 z-[7]">
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
      {showStandaloneTooltip && hovered != null ? (
        <div
          className="absolute z-[8] max-w-xs rounded-md border border-[#52575d] bg-black/95 px-2 py-1.5 shadow-lg"
          style={{
            left: Math.round(hoveredPaneX + hovered.diameterPx / 2 + 8),
            top: Math.round(hoveredPaneY - hovered.diameterPx / 2),
          }}
          role="tooltip"
        >
          <FleetLocationRingTooltipBody stack={hovered} />
        </div>
      ) : null}
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
