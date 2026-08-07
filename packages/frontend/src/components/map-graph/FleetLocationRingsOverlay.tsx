import { useMemo, useState } from 'react'
import { useStore } from '@xyflow/react'
import { HullIcon } from '../HullIcon'
import {
  buildFleetLocationRingStacks,
  collectFleetLocationRingShips,
  fleetLocationRingPaintRadiusPx,
  FLEET_LOCATION_RING_DEFAULT_STRENGTH_SCALE,
  type FleetLocationRingPlayerArc,
  type FleetLocationRingStack,
} from '../../analytics/fleet/fleetLocationRings'
import { useFleetStreamPlayersById } from '../../analytics/fleet/FleetStreamPlayersContext'
import { useFleetComponentCatalogQuery } from '../../analytics/fleet/useFleetComponentCatalogQuery'
import { useOrderedFleetPlayers } from '../../analytics/fleet/useOrderedFleetPlayers'
import type { AnalyticShellScope } from '../../api/bff'
import { usePlayerColor } from '../../stores/playerColors'
import { flowCenterFromMapNode, safeZoomScale } from './geometry'
import { useOverlayPaneSize } from './useOverlayPaneSize'

type FleetLocationRingsOverlayProps = {
  analyticScope: AnalyticShellScope
  /** When false, paint nothing (fleet analytic disabled). */
  enabled: boolean
}

/**
 * Screen-fixed fleet location rings from the shared fleet stream.
 * Geometry is not mergeLayer planet nodes; paint is independent of zoom LY scale.
 */
export function FleetLocationRingsOverlay({
  analyticScope,
  enabled,
}: FleetLocationRingsOverlayProps) {
  const streamPlayersById = useFleetStreamPlayersById()
  const domNode = useStore((s) => s.domNode ?? null)
  const transform = useStore((s) => s.transform)
  const { width, height } = useOverlayPaneSize(domNode)
  const { players: visiblePlayers } = useOrderedFleetPlayers({ visibleOnly: true })
  const componentCatalog = useFleetComponentCatalogQuery(analyticScope, enabled)
  const [hoveredKey, setHoveredKey] = useState<string | null>(null)

  const stacks = useMemo(() => {
    if (!enabled) {
      return []
    }
    const ships = collectFleetLocationRingShips(
      streamPlayersById,
      visiblePlayers.map((player) => ({
        playerId: player.playerId,
        name: player.name,
      })),
      componentCatalog,
      analyticScope.turn
    )
    return buildFleetLocationRingStacks(ships, FLEET_LOCATION_RING_DEFAULT_STRENGTH_SCALE)
  }, [
    enabled,
    streamPlayersById,
    visiblePlayers,
    componentCatalog,
    analyticScope.turn,
  ])

  if (!enabled || !transform || width <= 0 || height <= 0 || stacks.length === 0) {
    return null
  }

  const [tx, ty, rawScale] = transform
  const scale = safeZoomScale(rawScale)
  const hovered = hoveredKey != null ? stacks.find((s) => s.key === hoveredKey) : null
  let hoveredPaneX = 0
  let hoveredPaneY = 0
  if (hovered != null) {
    const { cx, cy } = flowCenterFromMapNode({ x: hovered.x, y: hovered.y })
    hoveredPaneX = cx * scale + tx
    hoveredPaneY = cy * scale + ty
  }

  return (
    <div className="pointer-events-none absolute inset-0 z-[7]">
      <svg className="h-full w-full" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        {stacks.map((stack) => {
          const { cx, cy } = flowCenterFromMapNode({ x: stack.x, y: stack.y })
          const paneX = cx * scale + tx
          const paneY = cy * scale + ty
          const outerRadius = stack.diameterPx / 2
          const paintRadius = fleetLocationRingPaintRadiusPx(stack.diameterPx, stack.strokeWidthPx)
          const circumference = 2 * Math.PI * paintRadius
          let dashOffset = 0
          return (
            <g key={stack.key} transform={`translate(${paneX} ${paneY})`}>
              {/* Hit target for hover (SVG pointer events). */}
              <circle
                cx={0}
                cy={0}
                r={outerRadius + 4}
                fill="transparent"
                className="pointer-events-auto cursor-default"
                onMouseEnter={() => setHoveredKey(stack.key)}
                onMouseLeave={() =>
                  setHoveredKey((current) => (current === stack.key ? null : current))
                }
              />
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
      {hovered != null ? (
        <FleetLocationRingTooltip
          stack={hovered}
          paneX={hoveredPaneX}
          paneY={hoveredPaneY}
        />
      ) : null}
    </div>
  )
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

function FleetLocationRingTooltip({
  stack,
  paneX,
  paneY,
}: {
  stack: FleetLocationRingStack
  paneX: number
  paneY: number
}) {
  return (
    <div
      className="pointer-events-none absolute z-[8] max-w-xs rounded-md border border-[#52575d] bg-black/95 px-2 py-1.5 font-mono text-[10px] text-slate-200 shadow-lg"
      style={{
        left: Math.round(paneX + stack.diameterPx / 2 + 8),
        top: Math.round(paneY - stack.diameterPx / 2),
      }}
      role="tooltip"
    >
      {stack.arcs.map((arc) => (
        <FleetLocationRingTooltipPlayer key={arc.playerId} arc={arc} />
      ))}
    </div>
  )
}

function FleetLocationRingTooltipPlayer({ arc }: { arc: FleetLocationRingPlayerArc }) {
  const color = usePlayerColor(arc.playerId)
  return (
    <div className="mb-1 last:mb-0">
      <div className="font-medium" style={{ color }}>
        {arc.playerName}
      </div>
      <ul className="mt-0.5 space-y-0.5 pl-3">
        {arc.ships.map((ship) => (
          <li key={ship.recordId} className="flex items-center gap-1.5 text-slate-300">
            {ship.hullId != null ? (
              <HullIcon hullId={ship.hullId} className="h-4 w-4 shrink-0" />
            ) : (
              <span className="inline-block h-4 w-4 shrink-0" aria-hidden />
            )}
            <span className="truncate">
              {ship.shipIdLabel} · {ship.hullLabel} ·{' '}
              {ship.hostMilitaryPoints != null
                ? `${formatHostPoints(ship.hostMilitaryPoints)} mil`
                : '— mil'}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function formatHostPoints(points: number): string {
  return Number.isInteger(points) ? String(points) : points.toFixed(1)
}
