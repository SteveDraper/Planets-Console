/**
 * Dedicated minefield map pane (ADR 0030): isolated plus-lighter fills,
 * then source-over 1px screen-stable strokes.
 */

import { useMemo } from 'react'
import { useStore } from '@xyflow/react'
import type { CombinedMapData } from '../../api/bff'
import {
  minefieldTypePreferences,
  resolveMinefieldPaintColor,
} from '../../analytics/minefields/minefieldPaint'
import {
  minefieldPaintOps,
  type MinefieldFillOp,
  type MinefieldStrokeOp,
} from '../../analytics/minefields/minefieldPaintOps'
import { minefieldTypeId } from '../../analytics/minefields/types'
import type { KnownMinefield } from '../../analytics/minefields/wireSchema'
import { useMinefieldsPreferencesStore } from '../../stores/minefieldsPreferences'
import { usePlayerColorsStore } from '../../stores/playerColors'
import {
  flowToPane,
  gameMapCellCenterToFlow,
  type CartographyOverlayViewport,
} from '../../lib/cartography/cartographyOverlayGeometry'
import { safeZoomScale } from './geometry'
import { mapPaneZClass } from './mapPaneZOrder'
import { useOverlayPaneSize } from './useOverlayPaneSize'

function annulusPath(cx: number, cy: number, outerR: number, innerR: number): string {
  return [
    `M ${cx} ${cy}`,
    `m ${-outerR} 0`,
    `a ${outerR} ${outerR} 0 1 1 ${outerR * 2} 0`,
    `a ${outerR} ${outerR} 0 1 1 ${-outerR * 2} 0`,
    `M ${cx} ${cy}`,
    `m ${-innerR} 0`,
    `a ${innerR} ${innerR} 0 1 0 ${innerR * 2} 0`,
    `a ${innerR} ${innerR} 0 1 0 ${-innerR * 2} 0`,
  ].join(' ')
}

export function MinefieldMapPane({
  minefields,
  shellTurn,
}: {
  minefields: CombinedMapData['minefields']
  shellTurn: number
}) {
  const domNode = useStore((s) => s.domNode ?? null)
  const transform = useStore((s) => s.transform)
  const { width, height } = useOverlayPaneSize(domNode)
  const types = useMinefieldsPreferencesStore((s) => s.types)
  const paintSnapshot = usePlayerColorsStore((s) => s.paintSnapshot)
  const viewpointPlayerId = usePlayerColorsStore((s) => s.viewpointPlayerId)
  const inbound = usePlayerColorsStore((s) => s.inboundRelationFromByPlayerId)

  const visible = useMemo(
    () => minefields.filter((field) => types[minefieldTypeId(field.isWeb)].enabled),
    [minefields, types]
  )

  if (!transform || width <= 0 || height <= 0 || visible.length === 0) {
    return null
  }

  const [tx, ty, rawScale] = transform
  const scale = safeZoomScale(rawScale)
  const viewport: CartographyOverlayViewport = { width, height, tx, ty, scale }
  const strokeWidth = 1
  const painted = visible.map((field) => {
    const geo = minefieldPaneGeometry(field, viewport)
    return {
      id: field.id,
      color: resolveMinefieldPaintColor({
        isWeb: field.isWeb,
        ownerId: field.ownerId,
        preferences: minefieldTypePreferences(types, field.isWeb),
        paintSnapshot,
        viewpointPlayerId,
        inboundRelationFromByPlayerId: inbound,
      }),
      geo,
      ops: minefieldPaintOps(geo.preR, geo.postR, field.infoTurn < shellTurn),
    }
  })
  const strokes = [...painted].sort((a, b) => a.id - b.id)

  return (
    <div
      className={`pointer-events-none absolute inset-0 ${mapPaneZClass('minefields')}`}
      style={{ isolation: 'isolate' }}
      aria-hidden
    >
      <svg className="h-full w-full" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        <g style={{ mixBlendMode: 'plus-lighter' }}>
          {painted.map((item) => (
            <MinefieldFills
              key={`fill-${item.id}`}
              cx={item.geo.cx}
              cy={item.geo.cy}
              color={item.color}
              fills={item.ops.fills}
            />
          ))}
        </g>
        <g>
          {strokes.map((item) => (
            <MinefieldStrokes
              key={`stroke-${item.id}`}
              cx={item.geo.cx}
              cy={item.geo.cy}
              color={item.color}
              strokeWidth={strokeWidth}
              strokes={item.ops.strokes}
            />
          ))}
        </g>
      </svg>
    </div>
  )
}

function MinefieldFills({
  cx,
  cy,
  color,
  fills,
}: {
  cx: number
  cy: number
  color: string
  fills: readonly MinefieldFillOp[]
}) {
  if (fills.length === 0) return null
  const nodes = fills.map((fill, index) =>
    fill.kind === 'disk' ? (
      <circle
        key={index}
        cx={cx}
        cy={cy}
        r={fill.radius}
        fill={color}
        fillOpacity={fill.opacity}
        stroke="none"
      />
    ) : (
      <path
        key={index}
        d={annulusPath(cx, cy, fill.outerRadius, fill.innerRadius)}
        fill={color}
        fillOpacity={fill.opacity}
        fillRule="evenodd"
        stroke="none"
      />
    )
  )
  return nodes.length === 1 ? nodes[0] : <g>{nodes}</g>
}

function MinefieldStrokes({
  cx,
  cy,
  color,
  strokeWidth,
  strokes,
}: {
  cx: number
  cy: number
  color: string
  strokeWidth: number
  strokes: readonly MinefieldStrokeOp[]
}) {
  if (strokes.length === 0) return null
  const nodes = strokes.map((stroke, index) => (
    <circle
      key={index}
      cx={cx}
      cy={cy}
      r={stroke.radius}
      fill="none"
      stroke={color}
      strokeOpacity={stroke.opacity}
      strokeWidth={strokeWidth}
      strokeDasharray={stroke.dasharray}
    />
  ))
  return nodes.length === 1 ? nodes[0] : <g>{nodes}</g>
}

function minefieldPaneGeometry(
  field: KnownMinefield,
  viewport: CartographyOverlayViewport
): { cx: number; cy: number; preR: number; postR: number } {
  const flow = gameMapCellCenterToFlow(field.x, field.y)
  const pane = flowToPane(flow.cx, flow.cy, viewport)
  return {
    cx: pane.px,
    cy: pane.py,
    preR: field.preRadius * viewport.scale,
    postR: field.postRadius * viewport.scale,
  }
}
