import { useCallback, useContext } from 'react'
import { BaseEdge, getStraightPath, useReactFlow, useStore, type EdgeProps } from '@xyflow/react'
import { shallow } from 'zustand/shallow'
import {
  WORMHOLE_EDGE_OPACITY,
  WORMHOLE_LINE_STROKE,
} from '../../lib/cartography/stellarCartographyTheme'
import { NODE_SIZE_FLOW, clientToFlowPosition, safeZoomScale } from './geometry'
import {
  WormholeHoverContext,
  WormholeLineRevealContext,
  WormholeRecenterPulseContext,
  recenterMapOnWormholeGameCell,
} from './stellarCartographyWormholeInteraction'

export type WormholeEdgeData = {
  isBidirectional?: boolean
  sourceGameX?: number
  sourceGameY?: number
  targetGameX?: number
  targetGameY?: number
  wormholeExitOnly?: boolean
}

export function wormholeHoverLabel(
  data: WormholeEdgeData | undefined,
  nearSource: boolean
): string | null {
  if (data == null) return null
  const sx = data.sourceGameX
  const sy = data.sourceGameY
  const tx = data.targetGameX
  const ty = data.targetGameY
  if (sx == null || sy == null || tx == null || ty == null) return null
  if (data.isBidirectional === true) {
    if (nearSource) return `goes to (${tx}, ${ty})`
    return `goes to (${sx}, ${sy})`
  }
  if (nearSource) return `goes to (${tx}, ${ty})`
  return `exit - entrance at (${sx}, ${sy})`
}

/** Stellar Cartography wormhole edge: sky line, mono arrowhead, click recenter, hover label. */
export function WormholeEdgeOnePixel(props: EdgeProps) {
  const { setViewport, getViewport } = useReactFlow()
  const { sourceNode, targetNode, zoom, domNode, transform } = useStore(
    (s) => ({
      sourceNode: s.nodeLookup.get(props.source),
      targetNode: s.nodeLookup.get(props.target),
      zoom: s.transform[2],
      domNode: s.domNode ?? null,
      transform: s.transform,
    }),
    shallow
  )
  const scale = safeZoomScale(zoom)
  const half = NODE_SIZE_FLOW / 2
  const sourceX = sourceNode ? sourceNode.position.x + half : props.sourceX
  const sourceY = sourceNode ? sourceNode.position.y + half : props.sourceY
  const targetX = targetNode ? targetNode.position.x + half : props.targetX
  const targetY = targetNode ? targetNode.position.y + half : props.targetY
  const [path] = getStraightPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
  })
  const data = props.data as WormholeEdgeData | undefined
  const isBidirectional = data?.isBidirectional !== false
  const setWormholeHover = useContext(WormholeHoverContext)
  const pulseWormholeAt = useContext(WormholeRecenterPulseContext)
  const lineReveal = useContext(WormholeLineRevealContext)

  const handlePointer = useCallback(
    (clientX: number, clientY: number): boolean => {
      const flow = clientToFlowPosition(clientX, clientY, domNode, transform)
      if (!flow) return false
      const distSource = Math.hypot(flow.x - sourceX, flow.y - sourceY)
      const distTarget = Math.hypot(flow.x - targetX, flow.y - targetY)
      return distSource <= distTarget
    },
    [domNode, transform, sourceX, sourceY, targetX, targetY]
  )

  const arrowHeadLen = 8 / scale
  const arrowAngle = Math.atan2(targetY - sourceY, targetX - sourceX)
  const arrowA1 = arrowAngle + Math.PI - Math.PI / 7
  const arrowA2 = arrowAngle + Math.PI + Math.PI / 7
  const arrowHx1 = targetX + arrowHeadLen * Math.cos(arrowA1)
  const arrowHy1 = targetY + arrowHeadLen * Math.sin(arrowA1)
  const arrowHx2 = targetX + arrowHeadLen * Math.cos(arrowA2)
  const arrowHy2 = targetY + arrowHeadLen * Math.sin(arrowA2)

  return (
    <>
      <BaseEdge
        path={path}
        interactionWidth={12}
        style={{
          stroke: WORMHOLE_LINE_STROKE,
          strokeWidth: 1 / scale,
          opacity: WORMHOLE_EDGE_OPACITY,
          strokeDasharray: `${5 / scale} ${4 / scale}`,
        }}
        onMouseMove={(e) => {
          lineReveal.cancelClear()
          const nearSource = handlePointer(e.clientX, e.clientY)
          const sx = data?.sourceGameX
          const sy = data?.sourceGameY
          const tx = data?.targetGameX
          const ty = data?.targetGameY
          if (sx != null && sy != null && tx != null && ty != null) {
            lineReveal.revealAt(nearSource ? tx : sx, nearSource ? ty : sy)
          }
          const label = wormholeHoverLabel(data, nearSource)
          setWormholeHover(label != null ? [label] : null)
        }}
        onMouseLeave={() => {
          setWormholeHover(null)
          lineReveal.scheduleClear()
        }}
        onClick={(e) => {
          const nearSource = handlePointer(e.clientX, e.clientY)
          const sx = data?.sourceGameX
          const sy = data?.sourceGameY
          const tx = data?.targetGameX
          const ty = data?.targetGameY
          if (sx == null || sy == null || tx == null || ty == null) return
          const recenterGame = nearSource ? { x: tx, y: ty } : { x: sx, y: sy }
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
      />
      {!isBidirectional ? (
        <polygon
          points={`${targetX},${targetY} ${arrowHx1},${arrowHy1} ${arrowHx2},${arrowHy2}`}
          fill={WORMHOLE_LINE_STROKE}
          opacity={WORMHOLE_EDGE_OPACITY}
          style={{ pointerEvents: 'none' }}
        />
      ) : null}
    </>
  )
}
