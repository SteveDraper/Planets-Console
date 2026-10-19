/**
 * Screen-fixed fleet location rings paint. Descriptive hover is owned by the
 * **map interaction surface** (no pointer capture, no overlay tooltip).
 * Emphasised arcs paint at full opacity with a thin contrasting outline.
 * Temporary stacks are emphasis-only and do not alter rest stacks.
 */

import { useStore } from '@xyflow/react'
import {
  FLEET_LOCATION_RING_EMPHASIS_OPACITY,
  FLEET_LOCATION_RING_EMPHASIS_OUTLINE_PX,
  fleetLocationRingArcEmphasis,
  fleetLocationRingEmphasisOutlineColor,
} from '../../analytics/fleet/fleetLocationRingEmphasis'
import {
  fleetLocationRingPaintRadiusPx,
  type FleetLocationRingStack,
} from '../../analytics/fleet/fleetLocationRings'
import { usePlayerColor } from '../../stores/playerColors'
import { flowCenterFromMapNode, safeZoomScale } from './geometry'
import { mapPaneZClass } from './mapPaneZOrder'
import { useOverlayPaneSize } from './useOverlayPaneSize'

const NO_EMPHASISED_PLAYER_IDS: ReadonlySet<number> = new Set()

type FleetLocationRingsOverlayProps = {
  stacks: readonly FleetLocationRingStack[]
  temporaryStacks?: readonly FleetLocationRingStack[]
  emphasisedPlayerIds?: ReadonlySet<number>
}

export function FleetLocationRingsOverlay({
  stacks,
  temporaryStacks = [],
  emphasisedPlayerIds = NO_EMPHASISED_PLAYER_IDS,
}: FleetLocationRingsOverlayProps) {
  const domNode = useStore((s) => s.domNode ?? null)
  const transform = useStore((s) => s.transform)
  const { width, height } = useOverlayPaneSize(domNode)

  if (
    !transform ||
    width <= 0 ||
    height <= 0 ||
    (stacks.length === 0 && temporaryStacks.length === 0)
  ) {
    return null
  }

  const [tx, ty, rawScale] = transform
  const scale = safeZoomScale(rawScale)
  const layers = [
    { id: 'rest', stacks },
    { id: 'temporary', stacks: temporaryStacks },
  ]

  return (
    <div className={`pointer-events-none absolute inset-0 ${mapPaneZClass('fleetLocationRings')}`}>
      <svg
        className="h-full w-full"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        aria-hidden
      >
        {layers.map((layer) =>
          layer.stacks.map((stack) => {
            const { cx, cy } = flowCenterFromMapNode({ x: stack.x, y: stack.y })
            const paneX = cx * scale + tx
            const paneY = cy * scale + ty
            return (
              <FleetLocationRingGlyph
                key={`${layer.id}:${stack.key}`}
                stack={stack}
                paneX={paneX}
                paneY={paneY}
                layer={layer.id}
                emphasisedPlayerIds={emphasisedPlayerIds}
              />
            )
          })
        )}
      </svg>
    </div>
  )
}

function layoutFleetLocationRingArcs(
  arcs: FleetLocationRingStack['arcs'],
  circumference: number
) {
  const layout: {
    playerId: number
    dash: number
    gap: number
    offset: number
  }[] = []
  let offset = 0
  for (const arc of arcs) {
    const dash = arc.share * circumference
    layout.push({
      playerId: arc.playerId,
      dash,
      gap: Math.max(0, circumference - dash),
      offset,
    })
    offset += dash
  }
  return layout
}

function FleetLocationRingGlyph({
  stack,
  paneX,
  paneY,
  layer,
  emphasisedPlayerIds,
}: {
  stack: FleetLocationRingStack
  paneX: number
  paneY: number
  layer: string
  emphasisedPlayerIds: ReadonlySet<number>
}) {
  const paintRadius = fleetLocationRingPaintRadiusPx(stack.diameterPx, stack.strokeWidthPx)
  const circumference = 2 * Math.PI * paintRadius
  const arcs = layoutFleetLocationRingArcs(stack.arcs, circumference)
  return (
    <g data-fleet-ring-layer={layer} transform={`translate(${paneX} ${paneY})`}>
      <g transform="rotate(-90)">
        {arcs.map((arc) => {
          const emphasis = fleetLocationRingArcEmphasis(arc.playerId, emphasisedPlayerIds)
          return (
            <FleetLocationRingArcStroke
              key={arc.playerId}
              playerId={arc.playerId}
              paintRadius={paintRadius}
              strokeWidthPx={stack.strokeWidthPx}
              dash={arc.dash}
              gap={arc.gap}
              dashOffset={arc.offset}
              opacity={
                emphasis === 'emphasis' ? FLEET_LOCATION_RING_EMPHASIS_OPACITY : stack.opacity
              }
              emphasised={emphasis === 'emphasis'}
            />
          )
        })}
      </g>
    </g>
  )
}

function FleetLocationRingArcStroke({
  playerId,
  paintRadius,
  strokeWidthPx,
  dash,
  gap,
  dashOffset,
  opacity,
  emphasised,
}: {
  playerId: number
  paintRadius: number
  strokeWidthPx: number
  dash: number
  gap: number
  dashOffset: number
  opacity: number
  emphasised: boolean
}) {
  const color = usePlayerColor(playerId)
  const dasharray = `${dash} ${gap}`
  const dashoffset = -dashOffset
  const outlineColor = emphasised ? fleetLocationRingEmphasisOutlineColor(color) : null
  return (
    <g opacity={opacity}>
      {outlineColor != null ? (
        <circle
          data-emphasis-outline=""
          cx={0}
          cy={0}
          r={paintRadius}
          fill="none"
          stroke={outlineColor}
          strokeWidth={strokeWidthPx + 2 * FLEET_LOCATION_RING_EMPHASIS_OUTLINE_PX}
          strokeDasharray={dasharray}
          strokeDashoffset={dashoffset}
          strokeLinecap="butt"
        />
      ) : null}
      <circle
        data-player-id={playerId}
        data-emphasis={emphasised ? 'emphasis' : 'rest'}
        cx={0}
        cy={0}
        r={paintRadius}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidthPx}
        strokeDasharray={dasharray}
        strokeDashoffset={dashoffset}
        strokeLinecap="butt"
      />
    </g>
  )
}
