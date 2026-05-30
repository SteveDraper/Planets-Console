import type { CSSProperties } from 'react'
import { BaseEdge, getStraightPath, useStore, type Edge, type EdgeProps } from '@xyflow/react'
import { shallow } from 'zustand/shallow'
import type { CombinedMapData } from '../../api/bff'
import { NODE_SIZE_FLOW, flowCenterFromMapNode, safeZoomScale } from './geometry'
import {
  WormholeEdgeOnePixel,
  type WormholeEdgeData,
} from './stellarCartographyWormholeEdge'

export type MapEdgeData = {
  viaFlare?: boolean
  waypointsInGame?: { x: number; y: number }[]
}

/** Custom edge keeps endpoints centered on dot nodes and stays visually 1px while zooming. */
export function StraightEdgeOnePixel(props: EdgeProps) {
  const { sourceNode, targetNode, zoom } = useStore(
    (s) => {
      const nodeLookup = s.nodeLookup
      return {
        sourceNode: nodeLookup.get(props.source),
        targetNode: nodeLookup.get(props.target),
        zoom: s.transform[2],
      }
    },
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

  const viaFlare =
    props.data != null &&
    typeof props.data === 'object' &&
    (props.data as { viaFlare?: boolean }).viaFlare === true

  return (
    <BaseEdge
      path={path}
      style={{
        stroke: viaFlare ? '#facc15' : '#b1b1b7',
        strokeWidth: 1 / scale,
        opacity: 0.5,
        ...(viaFlare ? { strokeDasharray: `${4 / scale} ${3 / scale}` } : {}),
      }}
    />
  )
}

const FLOW_POINT_EPS = 1e-6

function dedupeConsecutiveFlowPoints(points: { x: number; y: number }[]): {
  x: number
  y: number
}[] {
  const out: { x: number; y: number }[] = []
  for (const p of points) {
    const last = out[out.length - 1]
    if (last == null || Math.hypot(p.x - last.x, p.y - last.y) > FLOW_POINT_EPS) {
      out.push(p)
    }
  }
  return out
}

function buildSvgPathThroughFlowPoints(points: { x: number; y: number }[]): string {
  if (points.length < 2) return ''
  let d = `M ${points[0].x} ${points[0].y}`
  for (let i = 1; i < points.length; i += 1) {
    d += ` L ${points[i].x} ${points[i].y}`
  }
  return d
}

/**
 * Multi-segment map edge: source -> optional game-cell waypoints -> target, 1px on screen,
 * same style as `StraightEdgeOnePixel`.
 */
export function PolylineEdgeOnePixel(props: EdgeProps) {
  const { sourceNode, targetNode, zoom } = useStore(
    (s) => {
      const nodeLookup = s.nodeLookup
      return {
        sourceNode: nodeLookup.get(props.source),
        targetNode: nodeLookup.get(props.target),
        zoom: s.transform[2],
      }
    },
    shallow
  )
  const scale = safeZoomScale(zoom)
  const half = NODE_SIZE_FLOW / 2
  const data = props.data as MapEdgeData | undefined
  const wps = data?.waypointsInGame
  const viaFlare = data?.viaFlare === true
  const mapEdgeStrokeStyle: CSSProperties = {
    stroke: viaFlare ? '#facc15' : '#b1b1b7',
    strokeWidth: 1 / scale,
    opacity: 0.5,
    ...(viaFlare ? { strokeDasharray: `${4 / scale} ${3 / scale}` } : {}),
  }
  if (!sourceNode || !targetNode) {
    const [path] = getStraightPath({
      sourceX: props.sourceX,
      sourceY: props.sourceY,
      targetX: props.targetX,
      targetY: props.targetY,
    })
    return <BaseEdge path={path} style={mapEdgeStrokeStyle} />
  }
  const sCx = sourceNode.position.x + half
  const sCy = sourceNode.position.y + half
  const tCx = targetNode.position.x + half
  const tCy = targetNode.position.y + half
  const flowPoints = dedupeConsecutiveFlowPoints([
    { x: sCx, y: sCy },
    ...(Array.isArray(wps)
      ? wps.map((g) => {
          const { cx, cy } = flowCenterFromMapNode({ x: g.x, y: g.y })
          return { x: cx, y: cy }
        })
      : []),
    { x: tCx, y: tCy },
  ])
  if (flowPoints.length < 2) {
    const [path] = getStraightPath({
      sourceX: sCx,
      sourceY: sCy,
      targetX: tCx,
      targetY: tCy,
    })
    return <BaseEdge path={path} style={mapEdgeStrokeStyle} />
  }
  const path = buildSvgPathThroughFlowPoints(flowPoints)
  return <BaseEdge path={path} style={mapEdgeStrokeStyle} />
}

export const edgeTypes = {
  straight: StraightEdgeOnePixel,
  polyline: PolylineEdgeOnePixel,
  wormhole: WormholeEdgeOnePixel,
}

export function toEdges(edges: CombinedMapData['edges']): Edge[] {
  return edges.map((e, i) => {
    if (e.layer === 'wormholes') {
      return {
        id: `e-${e.source}-${e.target}-${i}`,
        source: e.source,
        target: e.target,
        sourceHandle: 's',
        targetHandle: 't',
        type: 'wormhole',
        data: {
          isBidirectional: e.isBidirectional,
          sourceGameX: e.sourceGameX,
          sourceGameY: e.sourceGameY,
          targetGameX: e.targetGameX,
          targetGameY: e.targetGameY,
          wormholeExitOnly: e.wormholeExitOnly,
        } satisfies WormholeEdgeData,
      }
    }
    const wps = e.waypointsInGame
    const hasPoly = Array.isArray(wps) && wps.length > 0
    return {
      id: `e-${e.source}-${e.target}-${i}`,
      source: e.source,
      target: e.target,
      sourceHandle: 's',
      targetHandle: 't',
      type: hasPoly ? 'polyline' : 'straight',
      data: {
        viaFlare: e.viaFlare === true,
        ...(hasPoly ? { waypointsInGame: wps } : {}),
      } satisfies MapEdgeData,
    }
  })
}
