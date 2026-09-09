/**
 * Dedicated minefield map pane (ADR 0030): isolated plus-lighter fills,
 * then source-over 1px screen-stable strokes.
 */

import { useMemo } from 'react'
import { useStore } from '@xyflow/react'
import type { CombinedMapData } from '../../api/bff'
import {
  ANNULUS_FILL_OPACITY,
  INTERIOR_FILL_OPACITY,
  STALE_FILL_OPACITY_FACTOR,
  STROKE_OPACITY,
  minefieldTypeId,
} from '../../analytics/minefields/types'
import {
  minefieldTypePreferences,
  resolveMinefieldPaintColor,
} from '../../analytics/minefields/minefieldPaint'
import type { KnownMinefield } from '../../analytics/minefields/wireSchema'
import { useMinefieldsPreferencesStore } from '../../stores/minefieldsPreferences'
import { usePlayerColorsStore } from '../../stores/playerColors'
import {
  flowToPane,
  gameMapCellCenterToFlow,
  type CartographyOverlayViewport,
} from '../../lib/cartography/cartographyOverlayGeometry'
import { safeZoomScale } from './geometry'
import { useOverlayPaneSize } from './useOverlayPaneSize'

function fillOpacity(base: number, stale: boolean): number {
  return stale ? base * STALE_FILL_OPACITY_FACTOR : base
}

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
  const strokes = [...visible].sort((a, b) => a.id - b.id)

  return (
    <div
      className="pointer-events-none absolute inset-0 z-[7]"
      style={{ isolation: 'isolate' }}
      aria-hidden
    >
      <svg className="h-full w-full" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        <g style={{ mixBlendMode: 'plus-lighter' }}>
          {visible.map((field) => (
            <MinefieldFills
              key={`fill-${field.id}`}
              field={field}
              color={resolveMinefieldPaintColor({
                isWeb: field.isWeb,
                ownerId: field.ownerId,
                preferences: minefieldTypePreferences(types, field.isWeb),
                paintSnapshot,
                viewpointPlayerId,
                inboundRelationFromByPlayerId: inbound,
              })}
              stale={field.infoTurn < shellTurn}
              viewport={viewport}
            />
          ))}
        </g>
        <g>
          {strokes.map((field) => (
            <MinefieldStrokes
              key={`stroke-${field.id}`}
              field={field}
              color={resolveMinefieldPaintColor({
                isWeb: field.isWeb,
                ownerId: field.ownerId,
                preferences: minefieldTypePreferences(types, field.isWeb),
                paintSnapshot,
                viewpointPlayerId,
                inboundRelationFromByPlayerId: inbound,
              })}
              viewport={viewport}
              strokeWidth={strokeWidth}
            />
          ))}
        </g>
      </svg>
    </div>
  )
}

function MinefieldFills({
  field,
  color,
  stale,
  viewport,
}: {
  field: KnownMinefield
  color: string
  stale: boolean
  viewport: CartographyOverlayViewport
}) {
  const { cx, cy, preR, postR } = minefieldPaneGeometry(field, viewport)
  if (preR <= 0) return null

  if (postR <= 0) {
    return (
      <circle
        cx={cx}
        cy={cy}
        r={preR}
        fill={color}
        fillOpacity={fillOpacity(ANNULUS_FILL_OPACITY, stale)}
        stroke="none"
      />
    )
  }

  const interior = (
    <circle
      cx={cx}
      cy={cy}
      r={postR}
      fill={color}
      fillOpacity={fillOpacity(INTERIOR_FILL_OPACITY, stale)}
      stroke="none"
    />
  )
  if (preR === postR) {
    return interior
  }
  return (
    <g>
      {interior}
      <path
        d={annulusPath(cx, cy, preR, postR)}
        fill={color}
        fillOpacity={fillOpacity(ANNULUS_FILL_OPACITY, stale)}
        fillRule="evenodd"
        stroke="none"
      />
    </g>
  )
}

function MinefieldStrokes({
  field,
  color,
  viewport,
  strokeWidth,
}: {
  field: KnownMinefield
  color: string
  viewport: CartographyOverlayViewport
  strokeWidth: number
}) {
  const { cx, cy, preR, postR } = minefieldPaneGeometry(field, viewport)
  if (preR <= 0) return null
  const dash = `${4} ${3}`

  if (postR <= 0) {
    return (
      <circle
        cx={cx}
        cy={cy}
        r={preR}
        fill="none"
        stroke={color}
        strokeOpacity={STROKE_OPACITY}
        strokeWidth={strokeWidth}
      />
    )
  }

  if (preR === postR) {
    return (
      <circle
        cx={cx}
        cy={cy}
        r={preR}
        fill="none"
        stroke={color}
        strokeOpacity={STROKE_OPACITY}
        strokeWidth={strokeWidth}
        strokeDasharray={dash}
      />
    )
  }

  return (
    <g>
      <circle
        cx={cx}
        cy={cy}
        r={preR}
        fill="none"
        stroke={color}
        strokeOpacity={STROKE_OPACITY}
        strokeWidth={strokeWidth}
      />
      <circle
        cx={cx}
        cy={cy}
        r={postR}
        fill="none"
        stroke={color}
        strokeOpacity={STROKE_OPACITY}
        strokeWidth={strokeWidth}
        strokeDasharray={dash}
      />
    </g>
  )
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
