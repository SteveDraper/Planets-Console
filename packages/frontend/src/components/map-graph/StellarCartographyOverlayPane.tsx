import { useContext, useEffect, useState } from 'react'
import { useReactFlow, useStore } from '@xyflow/react'
import type { CombinedMapData } from '../../api/bff'
import {
  buildStellarCartographyOverlayPaneShapes,
  type StellarCartographyOverlayRadialGradient,
} from '../../lib/stellarCartographyOverlay'
import {
  ionStormCloudPaneShapeToRasterField,
  nebulaCloudPaneShapeToRasterField,
} from '../../lib/cartographyRasterFieldOverlay'
import { WormholeEndpointIconMark } from '../../lib/wormholeEndpointIcon'
import {
  formatWormholeEndpointHoverLines,
  type WormholeEndpointHoverInfo,
  wormholeEndpointRecenterGameCoords,
  wormholeMapCellKey,
} from '../../lib/wormholeEndpointHover'
import { RasterFieldOverlay } from '../RasterFieldOverlay'
import { safeZoomScale } from './geometry'
import {
  WormholeHoverContext,
  WormholeLineRevealContext,
  WormholeRecenterPulseContext,
  type WormholeRecenterPulseTarget,
  recenterMapOnWormholeGameCell,
} from './stellarCartographyWormholeInteraction'

const STELLAR_CARTOGRAPHY_NODE_PREFIX = 'stellar-cartography:'

export function collectWormholeEndpoints(
  nodes: CombinedMapData['nodes'],
  unknownEntrances: CombinedMapData['wormholeUnknownEntrances']
): { x: number; y: number }[] {
  const seen = new Set<string>()
  const endpoints: { x: number; y: number }[] = []
  const add = (x: number, y: number) => {
    const key = `${x},${y}`
    if (seen.has(key)) return
    seen.add(key)
    endpoints.push({ x, y })
  }
  for (const node of nodes) {
    if (node.id.startsWith(STELLAR_CARTOGRAPHY_NODE_PREFIX)) {
      add(Number(node.x), Number(node.y))
    }
  }
  for (const entrance of unknownEntrances) {
    add(entrance.x, entrance.y)
  }
  return endpoints
}

function StellarCartographyRadialGradientDef({
  gradient,
  variant,
}: {
  gradient: StellarCartographyOverlayRadialGradient
  variant: 'core' | 'band'
}) {
  const innerStop = `${gradient.innerOffset * 100}%`
  if (variant === 'core') {
    return (
      <radialGradient id={gradient.id} cx="50%" cy="50%" r="50%">
        <stop offset="0%" stopColor={gradient.color} stopOpacity={gradient.peakOpacity} />
        <stop offset={innerStop} stopColor={gradient.color} stopOpacity={gradient.peakOpacity} />
        <stop offset="100%" stopColor={gradient.color} stopOpacity={gradient.edgeOpacity} />
      </radialGradient>
    )
  }
  return (
    <radialGradient id={gradient.id} cx="50%" cy="50%" r="50%">
      <stop offset="0%" stopColor={gradient.color} stopOpacity={0} />
      <stop offset={innerStop} stopColor={gradient.color} stopOpacity={0} />
      <stop offset={innerStop} stopColor={gradient.color} stopOpacity={gradient.peakOpacity} />
      <stop offset="100%" stopColor={gradient.color} stopOpacity={gradient.edgeOpacity} />
    </radialGradient>
  )
}

export function StellarCartographyOverlayPane({
  overlayCircles,
  wormholeEndpoints,
  wormholeEndpointHoverByCell,
  wormholeRecenterPulseTarget,
  blockedByPlanetHover,
  nuIonStorms,
}: {
  overlayCircles: CombinedMapData['overlayCircles']
  wormholeEndpoints: { x: number; y: number }[]
  wormholeEndpointHoverByCell: Map<string, WormholeEndpointHoverInfo>
  wormholeRecenterPulseTarget: WormholeRecenterPulseTarget | null
  blockedByPlanetHover: boolean
  nuIonStorms?: boolean
}) {
  const { setViewport, getViewport } = useReactFlow()
  const setWormholeHover = useContext(WormholeHoverContext)
  const pulseWormholeAt = useContext(WormholeRecenterPulseContext)
  const lineReveal = useContext(WormholeLineRevealContext)
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
  if (overlayCircles.length === 0 && wormholeEndpoints.length === 0) return null

  const [tx, ty, rawScale] = transform
  const scale = safeZoomScale(rawScale)
  const { width, height } = size
  const shapes = buildStellarCartographyOverlayPaneShapes(
    overlayCircles,
    wormholeEndpoints,
    {
      width,
      height,
      tx,
      ty,
      scale,
    },
    { cloudyIonStorms: nuIonStorms ?? true }
  )

  if (
    shapes.circles.length === 0 &&
    shapes.annuli.length === 0 &&
    shapes.nebulaClouds.length === 0 &&
    shapes.ionStormClouds.length === 0 &&
    shapes.debrisDiskBorders.length === 0 &&
    shapes.arrows.length === 0 &&
    shapes.wormholeMarkers.length === 0
  ) {
    return null
  }

  return (
    <div className="pointer-events-none absolute inset-0 z-[5]" aria-hidden>
      <svg className="h-full w-full" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        {shapes.nebulaClouds.map((shape) => (
          <RasterFieldOverlay key={shape.key} {...nebulaCloudPaneShapeToRasterField(shape)} />
        ))}
        {shapes.ionStormClouds.map((shape) => (
          <RasterFieldOverlay key={shape.key} {...ionStormCloudPaneShapeToRasterField(shape)} />
        ))}
        {shapes.circles.map(({ key, cx, cy, r, fill, stroke, strokeWidth, fillGradient }) => (
          <g key={key}>
            {fillGradient != null && (
              <defs>
                <StellarCartographyRadialGradientDef gradient={fillGradient} variant="core" />
              </defs>
            )}
            <circle
              cx={cx}
              cy={cy}
              r={r}
              fill={fillGradient != null ? `url(#${fillGradient.id})` : fill}
              stroke={stroke}
              strokeWidth={strokeWidth}
            />
          </g>
        ))}
        {shapes.annuli.map(
          ({
            key,
            cx,
            cy,
            coreR,
            bandR,
            coreFill,
            coreStroke,
            coreGradient,
            bandFill,
            bandStroke,
            strokeWidth,
            bandGradient,
          }) => (
            <g key={key}>
              {(bandGradient != null || coreGradient != null) && (
                <defs>
                  {bandGradient != null && (
                    <StellarCartographyRadialGradientDef gradient={bandGradient} variant="band" />
                  )}
                  {coreGradient != null && (
                    <StellarCartographyRadialGradientDef gradient={coreGradient} variant="core" />
                  )}
                </defs>
              )}
              <circle
                cx={cx}
                cy={cy}
                r={bandR}
                fill={bandGradient != null ? `url(#${bandGradient.id})` : bandFill}
                stroke={bandStroke}
                strokeWidth={strokeWidth}
              />
              <circle
                cx={cx}
                cy={cy}
                r={coreR}
                fill={coreGradient != null ? `url(#${coreGradient.id})` : coreFill}
                stroke={coreStroke ?? 'none'}
                strokeWidth={coreStroke != null ? strokeWidth : 0}
              />
            </g>
          )
        )}
        {shapes.debrisDiskBorders.map(({ key, cx, cy, r, fill, stroke, strokeWidth }) => (
          <circle
            key={key}
            cx={cx}
            cy={cy}
            r={r}
            fill={fill}
            stroke={stroke}
            strokeWidth={strokeWidth}
          />
        ))}
        {shapes.arrows.map(({ key, x1, y1, x2, y2, stroke, strokeWidth }) => {
          const angle = Math.atan2(y2 - y1, x2 - x1)
          const headLen = 6
          const a1 = angle + Math.PI - Math.PI / 7
          const a2 = angle + Math.PI + Math.PI / 7
          const hx1 = x2 + headLen * Math.cos(a1)
          const hy1 = y2 + headLen * Math.sin(a1)
          const hx2 = x2 + headLen * Math.cos(a2)
          const hy2 = y2 + headLen * Math.sin(a2)
          return (
            <g key={key}>
              <line
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                stroke={stroke}
                strokeWidth={strokeWidth}
              />
              <polygon points={`${x2},${y2} ${hx1},${hy1} ${hx2},${hy2}`} fill={stroke} />
            </g>
          )
        })}
      </svg>
      <div className="absolute inset-0" aria-hidden>
        {shapes.wormholeMarkers.map(({ key, cx, cy, diameterPx, mapX, mapY }) => {
          const half = diameterPx / 2
          const hoverInfo = wormholeEndpointHoverByCell.get(wormholeMapCellKey(mapX, mapY))
          const recenterGame =
            hoverInfo != null ? wormholeEndpointRecenterGameCoords(hoverInfo) : null
          const isPulseTarget =
            wormholeRecenterPulseTarget != null &&
            wormholeRecenterPulseTarget.mapX === mapX &&
            wormholeRecenterPulseTarget.mapY === mapY
          return (
            <div
              key={key}
              className={`absolute pointer-events-auto${recenterGame != null ? ' cursor-pointer' : ''}`}
              style={{
                left: cx - half,
                top: cy - half,
                width: diameterPx,
                height: diameterPx,
              }}
              onMouseEnter={() => {
                lineReveal.cancelClear()
                lineReveal.revealAt(mapX, mapY)
                if (blockedByPlanetHover || hoverInfo == null) return
                setWormholeHover(formatWormholeEndpointHoverLines(hoverInfo))
              }}
              onMouseLeave={() => {
                setWormholeHover(null)
                lineReveal.scheduleClear()
              }}
              onClick={(e) => {
                if (recenterGame == null) return
                recenterMapOnWormholeGameCell(
                  recenterGame.x,
                  recenterGame.y,
                  domNode,
                  getViewport,
                  setViewport,
                  pulseWormholeAt
                )
                e.stopPropagation()
              }}
            >
              <div
                key={isPulseTarget ? `pulse-${wormholeRecenterPulseTarget.token}` : 'idle'}
                className={`h-full w-full${isPulseTarget ? ' wormhole-recenter-pulse' : ''}`}
              >
                <WormholeEndpointIconMark />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
