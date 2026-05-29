import {
  type CSSProperties,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { shallow } from 'zustand/shallow'
import {
  BaseEdge,
  ReactFlow,
  Handle,
  Panel,
  Position,
  getStraightPath,
  useReactFlow,
  useStore,
  useStoreApi,
  type Node,
  type Edge,
  type EdgeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { CombinedMapData, RouteMapWaypoint, AnalyticShellScope } from '../api/bff'
import { StellarCartographyHoverPanel } from '../analytics/stellar-cartography/StellarCartographyHoverPanel'
import { RasterFieldOverlay } from './RasterFieldOverlay'
import type {
  CartographyLayerVisibility,
  StellarCartographySettingsGates,
} from '../analytics/stellar-cartography/layers'
import {
  filterWormholeEdgesForDisplayMode,
  type WormholeDisplayMode,
} from '../analytics/stellar-cartography/wormholeDisplayMode'
import {
  buildStellarCartographyOverlayPaneShapes,
  gameMapCellCenterToFlow,
  type StellarCartographyOverlayRadialGradient,
} from '../lib/stellarCartographyOverlay'
import {
  ionStormCloudPaneShapeToRasterField,
  nebulaCloudPaneShapeToRasterField,
} from '../lib/cartographyRasterFieldOverlay'
import {
  WORMHOLE_EDGE_OPACITY,
  WORMHOLE_LINE_STROKE,
  WORMHOLE_RECENTER_PULSE_MS,
} from '../lib/stellarCartographyTheme'
import { WormholeEndpointIconMark } from '../lib/wormholeEndpointIcon'
import {
  buildWormholeEndpointHoverIndex,
  formatWormholeEndpointHoverLines,
  type WormholeEndpointHoverInfo,
  wormholeEndpointRecenterGameCoords,
  wormholeMapCellKey,
} from '../lib/wormholeEndpointHover'
import {
  buildPlanetSpatialGrid,
  findClosestPlanetWithinRadius,
  flowCenterToPlanet,
  PLANET_CELL_CENTER_OFFSET,
  type PlanetSpatialGrid,
} from '../lib/planetSpatialGrid'
import { cn } from '../lib/utils'
import { PlanetMapLabel } from './PlanetMapLabel'
import {
  DEFAULT_PLANET_LABEL_OPTIONS,
  planetLabelOptionsShowAnyLabel,
  type PlanetLabelOptions,
} from './planetMapLabelModel'
import {
  buildWarpWellOverlayPaneLines,
  WARP_WELL_OVERLAY_ZOOM_THRESHOLD,
} from '../lib/warpWellOverlay'

const STELLAR_CARTOGRAPHY_NODE_PREFIX = 'stellar-cartography:'

function collectWormholeEndpoints(
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

type MapNodeData = {
  label?: string
  ordinal: number
  x: number
  y: number
  planet?: Record<string, unknown>
  ownerName?: string | null
}

/** Stable node size in flow space so React Flow keeps node measurements through zoom. */
const NODE_SIZE_FLOW = 12
/** Fixed pixel size of the planet dot on screen (independent of zoom). */
const DOT_PIXELS = 4
/** On-screen size of a multi-hop route intermediate marker (smaller and quieter than planet dots). */
const ROUTE_WAYPOINT_CROSS_PX = 5
/** Mouse distance from dot center (px) at which the planet label is shown. */
const PLANET_LABEL_HOVER_RADIUS_PX = 14
/** Offset so node and edge targets use the center of the map cell (0.5, 0.5) as demarcated by grid lines at integers. */
const CELL_CENTER_OFFSET = PLANET_CELL_CENTER_OFFSET

/** Flow Y for React Flow (y grows downward); smaller game y sits lower on screen. */
function gameMapYToFlowCenterY(py: number): number {
  return -(py + CELL_CENTER_OFFSET)
}

/** Fraction of display area to leave as blank margin on each side when fitting initial view (0.1 = 10%). */
const INITIAL_FIT_MARGIN = 0.1

function safeZoomScale(scale: number | undefined): number {
  return typeof scale === 'number' && Number.isFinite(scale) && scale > 0 ? scale : 1
}

/** Invisible handle at node center so edges connect to dot center. */
const centerHandleStyle: CSSProperties = {
  position: 'absolute',
  top: '50%',
  left: '50%',
  transform: 'translate(-50%, -50%)',
  opacity: 0,
  width: 12,
  height: 12,
  minWidth: 12,
  minHeight: 12,
  border: 'none',
  padding: 0,
  background: 'transparent',
  pointerEvents: 'none',
}

/** Invisible routing node; visible dot is drawn by the overlay. */
function DotNode() {
  return (
    <div
      className="relative"
      style={{ width: NODE_SIZE_FLOW, height: NODE_SIZE_FLOW, minWidth: NODE_SIZE_FLOW, minHeight: NODE_SIZE_FLOW }}
    >
      <Handle type="target" position={Position.Left} id="t" style={centerHandleStyle} />
      <Handle type="source" position={Position.Left} id="s" style={centerHandleStyle} />
      {/* Planet labels are rendered in a separate overlay to keep pixel-stable positioning. */}
    </div>
  )
}

const nodeTypes = { dot: DotNode }

const WormholeHoverContext = createContext<(lines: string[] | null) => void>(() => {})

export type WormholeRecenterPulseTarget = {
  mapX: number
  mapY: number
  token: number
}

const WormholeRecenterPulseContext = createContext<(mapX: number, mapY: number) => void>(() => {})

const WORMHOLE_LINE_REVEAL_CLEAR_MS = 120

type WormholeLineRevealApi = {
  revealAt: (mapX: number, mapY: number) => void
  scheduleClear: () => void
  cancelClear: () => void
}

const WormholeLineRevealContext = createContext<WormholeLineRevealApi>({
  revealAt: () => {},
  scheduleClear: () => {},
  cancelClear: () => {},
})

function recenterMapOnWormholeGameCell(
  gameX: number,
  gameY: number,
  domNode: HTMLElement | null,
  getViewport: () => { x: number; y: number; zoom: number },
  setViewport: (vp: { x: number; y: number; zoom: number }) => void,
  pulseAt: (mapX: number, mapY: number) => void
): void {
  const { cx, cy } = gameMapCellCenterToFlow(gameX, gameY)
  recenterViewportOnFlowPoint(cx, cy, domNode, getViewport, setViewport)
  pulseAt(gameX, gameY)
}

/** Custom edge keeps endpoints centered on dot nodes and stays visually 1px while zooming. */
function StraightEdgeOnePixel(props: EdgeProps) {
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

function dedupeConsecutiveFlowPoints(
  points: { x: number; y: number }[]
): { x: number; y: number }[] {
  const out: { x: number; y: number }[] = []
  for (const p of points) {
    const last = out[out.length - 1]
    if (last == null || Math.hypot(p.x - last.x, p.y - last.y) > FLOW_POINT_EPS) {
      out.push(p)
    }
  }
  return out
}

function buildSvgPathThroughFlowPoints(
  points: { x: number; y: number }[]
): string {
  if (points.length < 2) return ''
  let d = `M ${points[0].x} ${points[0].y}`
  for (let i = 1; i < points.length; i += 1) {
    d += ` L ${points[i].x} ${points[i].y}`
  }
  return d
}

type MapEdgeData = {
  viaFlare?: boolean
  waypointsInGame?: { x: number; y: number }[]
}

type WormholeEdgeData = {
  isBidirectional?: boolean
  sourceGameX?: number
  sourceGameY?: number
  targetGameX?: number
  targetGameY?: number
  wormholeExitOnly?: boolean
}

function wormholeHoverLabel(
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

function recenterViewportOnFlowPoint(
  flowX: number,
  flowY: number,
  domNode: HTMLElement | null,
  getViewport: () => { x: number; y: number; zoom: number },
  setViewport: (vp: { x: number; y: number; zoom: number }) => void
): void {
  if (!domNode) return
  const rect = domNode.getBoundingClientRect()
  const w = Math.max(rect.width, 1)
  const h = Math.max(rect.height, 1)
  const vp = getViewport()
  const z = Math.max(Number(vp.zoom) || 0.2, 0.2)
  setViewport({ x: w / 2 - flowX * z, y: h / 2 - flowY * z, zoom: z })
}

/** Stellar Cartography wormhole edge: sky line, mono arrowhead, click recenter, hover label. */
function WormholeEdgeOnePixel(props: EdgeProps) {
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

/**
 * Multi-segment map edge: source → (optional game-cell waypoints) → target, 1px on screen, same style as `StraightEdgeOnePixel`.
 */
function PolylineEdgeOnePixel(props: EdgeProps) {
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

const edgeTypes = {
  straight: StraightEdgeOnePixel,
  polyline: PolylineEdgeOnePixel,
  wormhole: WormholeEdgeOnePixel,
}

/** Map coordinates (px, py) are cell indices; node geometry stays fixed and centered on the map cell. */
function toFlowNodes(nodes: CombinedMapData['nodes']): Node<MapNodeData>[] {
  const half = NODE_SIZE_FLOW / 2
  return nodes.map((node, i) => {
    const x = Number(node.x)
    const y = Number(node.y)
    const px = Number.isFinite(x) ? x : 0
    const py = Number.isFinite(y) ? y : 0
    const cx = px + CELL_CENTER_OFFSET
    const cy = gameMapYToFlowCenterY(py)
    return {
      id: node.id,
      type: 'dot',
      position: { x: cx - half, y: cy - half },
      width: NODE_SIZE_FLOW,
      height: NODE_SIZE_FLOW,
      data: {
        label: node.label,
        ordinal: i + 1,
        x: px,
        y: py,
        planet: node.planet,
        ownerName: node.ownerName,
      },
    }
  })
}

function toEdges(edges: CombinedMapData['edges']): Edge[] {
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

/**
 * Converts client position to flow (graph) coordinates.
 * xyflow stores transform as [tx, ty, scale] where (tx, ty) is the *pane* position of the
 * flow origin, and uses flow = (pane - translation) / scale (see pointToRendererPoint usage).
 * We need the element whose (0,0) is the pane origin: the viewport or the flow container.
 */
function clientToFlowPosition(
  clientX: number,
  clientY: number,
  domNode: HTMLElement | null,
  transform: [number, number, number] | undefined,
  /** When supplied, avoids getBoundingClientRect (e.g. one rect per animation frame). */
  paneRect?: Pick<DOMRect, 'left' | 'top'>
): { x: number; y: number } | null {
  if (!domNode || !transform) return null
  const rect = paneRect ?? domNode.getBoundingClientRect()
  const [tx, ty, scale] = transform
  if (typeof scale !== 'number' || !Number.isFinite(scale) || scale <= 0) return null
  const paneX = clientX - rect.left
  const paneY = clientY - rect.top
  const x = (paneX - tx) / scale
  const y = (paneY - ty) / scale
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null
  return { x, y }
}

/**
 * Computes initial viewport so the bounding rectangle of all node centers is
 * centered with a 10% margin (whichever dimension is most constrained).
 * Runs once when the pane has size and nodes are present. Calls onInitialFitDone when done (or when no fit will run).
 */
function InitialViewportFit({
  nodes,
  onInitialFitDone,
  onMapZoomChange,
}: {
  nodes: CombinedMapData['nodes']
  onInitialFitDone: () => void
  onMapZoomChange: (zoom: number) => void
}) {
  const { setViewport } = useReactFlow()
  const domNode = useStore((s) => s.domNode ?? null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const hasFittedRef = useRef(false)
  const doneCalledRef = useRef(false)

  const callDoneOnce = useCallback(() => {
    if (doneCalledRef.current) return
    doneCalledRef.current = true
    onInitialFitDone()
  }, [onInitialFitDone])

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

  useEffect(() => {
    if (nodes.length === 0) {
      callDoneOnce()
      return
    }
    if (size.width <= 0 || size.height <= 0 || hasFittedRef.current) return
    const xs = nodes.map((n) => Number(n.x)).filter(Number.isFinite)
    const ys = nodes.map((n) => Number(n.y)).filter(Number.isFinite)
    if (xs.length === 0 || ys.length === 0) {
      callDoneOnce()
      return
    }
    const minFx = Math.min(...xs) + CELL_CENTER_OFFSET
    const maxFx = Math.max(...xs) + CELL_CENTER_OFFSET
    const flowCentersY = ys.map((py) => gameMapYToFlowCenterY(py))
    const minFy = Math.min(...flowCentersY)
    const maxFy = Math.max(...flowCentersY)
    const contentWidth = Math.max(maxFx - minFx, 1)
    const contentHeight = Math.max(maxFy - minFy, 1)
    const centerX = (minFx + maxFx) / 2
    const centerY = (minFy + maxFy) / 2
    const usableW = size.width * (1 - 2 * INITIAL_FIT_MARGIN)
    const usableH = size.height * (1 - 2 * INITIAL_FIT_MARGIN)
    const scaleW = usableW / contentWidth
    const scaleH = usableH / contentHeight
    const zoom = Math.min(40, Math.max(0.2, Math.min(scaleW, scaleH)))
    const x = size.width / 2 - centerX * zoom
    const y = size.height / 2 - centerY * zoom
    hasFittedRef.current = true
    setViewport({ x, y, zoom })
    onMapZoomChange(zoom)
    callDoneOnce()
  }, [nodes, size, setViewport, callDoneOnce, onMapZoomChange])

  return null
}

/**
 * Tracks mouse over the flow viewport and shows position in flow coordinates.
 * Attaches listeners to the store's domNode so we receive events regardless of
 * whether ReactFlow forwards onMouseMove. Must be rendered inside ReactFlow.
 */
function FlowCoordinateReadout() {
  const domNode = useStore((s) => s.domNode ?? null)
  const transform = useStore((s) => s.transform)
  const [clientPos, setClientPos] = useState<{ x: number; y: number } | null>(null)

  useEffect(() => {
    const el = domNode
    if (!el) return
    const onMove = (e: MouseEvent) => setClientPos({ x: e.clientX, y: e.clientY })
    const onLeave = () => setClientPos(null)
    el.addEventListener('mousemove', onMove)
    el.addEventListener('mouseleave', onLeave)
    return () => {
      el.removeEventListener('mousemove', onMove)
      el.removeEventListener('mouseleave', onLeave)
    }
  }, [domNode])

  const flow = clientPos
    ? clientToFlowPosition(clientPos.x, clientPos.y, domNode, transform)
    : null
  const scale = typeof transform?.[2] === 'number' && Number.isFinite(transform[2]) ? transform[2] : null

  const content =
    clientPos == null ? (
      scale != null ? <>zoom: {scale.toFixed(2)}</> : '—'
    ) : flow != null ? (
      <>
        x: {Math.floor(flow.x)} y: {Math.floor(-flow.y)} zoom: {scale != null ? scale.toFixed(2) : '—'}
      </>
    ) : (
      <>client: {Math.round(clientPos.x)}, {Math.round(clientPos.y)} zoom: {scale != null ? scale.toFixed(2) : '—'}</>
    )

  return (
    <Panel position="bottom-left" className="rounded bg-black/80 px-2 py-1 font-mono text-xs text-gray-300">
      {content}
    </Panel>
  )
}

/** Show grid when zoom >= this (pixels per flow unit). */
const GRID_ZOOM_THRESHOLD = 15

/** Light grey at 30% opacity so the warp-well overlay reads stronger when lines coincide. */
const GRID_STROKE = 'rgba(107, 114, 128, 0.3)'

/** Slightly warmer than the coordinate grid so both remain distinguishable. */
const WARP_WELL_STROKE = '#78716c'

/**
 * Coordinate grid overlay when zoomed in. Drawn in pixel space so lines stay 1px at any zoom;
 * flow positions converted to pane pixels via pane = flow * scale + translation.
 */
function CoordinateGridOverlay() {
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
  const [tx, ty, rawScale] = transform
  const scale = safeZoomScale(rawScale)
  if (scale < GRID_ZOOM_THRESHOLD) return null

  const { width, height } = size
  const flowXMin = -tx / scale
  const flowXMax = (width - tx) / scale
  const flowYMin = -ty / scale
  const flowYMax = (height - ty) / scale

  const xFrom = Math.floor(flowXMin)
  const xTo = Math.ceil(flowXMax)
  const yFrom = Math.floor(flowYMin)
  const yTo = Math.ceil(flowYMax)

  const verticals = Array.from({ length: xTo - xFrom + 1 }, (_, i) => {
    const flowX = xFrom + i
    const paneX = flowX * scale + tx
    return { key: `v${flowX}`, x: paneX }
  })
  const horizontals = Array.from({ length: yTo - yFrom + 1 }, (_, i) => {
    const flowY = yFrom + i
    const paneY = flowY * scale + ty
    return { key: `h${flowY}`, y: paneY }
  })

  return (
    <div
      className="pointer-events-none absolute inset-0 z-[5]"
      aria-hidden
    >
      <svg
        className="h-full w-full"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
      >
        <g stroke={GRID_STROKE} strokeWidth={1}>
          {verticals.map(({ key, x }) => (
            <line key={key} x1={x} y1={0} x2={x} y2={height} />
          ))}
          {horizontals.map(({ key, y }) => (
            <line key={key} x1={0} y1={y} x2={width} y2={y} />
          ))}
        </g>
      </svg>
    </div>
  )
}

function NormalWarpWellOutlinesOverlay({ mapNodes }: { mapNodes: CombinedMapData['nodes'] }) {
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
  const [tx, ty, rawScale] = transform
  const scale = safeZoomScale(rawScale)
  if (scale < WARP_WELL_OVERLAY_ZOOM_THRESHOLD) return null

  const { width, height } = size
  const lines = buildWarpWellOverlayPaneLines(
    mapNodes,
    { width, height, tx, ty, scale },
    WARP_WELL_OVERLAY_ZOOM_THRESHOLD
  )

  if (lines.length === 0) return null

  return (
    <div className="pointer-events-none absolute inset-0 z-[5]" aria-hidden>
      <svg className="h-full w-full" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        <g stroke={WARP_WELL_STROKE} strokeWidth={1}>
          {lines.map(({ key, x1, y1, x2, y2 }) => (
            <line key={key} x1={x1} y1={y1} x2={x2} y2={y2} />
          ))}
        </g>
      </svg>
    </div>
  )
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

function StellarCartographyOverlay({
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
  const shapes = buildStellarCartographyOverlayPaneShapes(overlayCircles, wormholeEndpoints, {
    width,
    height,
    tx,
    ty,
    scale,
  }, { cloudyIonStorms: nuIonStorms ?? true })

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
                fill={
                  coreGradient != null ? `url(#${coreGradient.id})` : coreFill
                }
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

/**
 * in size regardless of zoom. Uses same flow->pane conversion as the grid.
 */
const HOVER_CLIENT_MOVE_EPS_PX = 0.5

/** Label text uses map payload (planet name, etc.). React Flow's internal node store does not reliably retain custom `data` fields. */
type MapNodeLabelSource = {
  planet?: Record<string, unknown>
  ownerName?: string | null
  mapX: number
  mapY: number
}

function buildLabelSourceByNodeId(nodes: CombinedMapData['nodes']): Map<string, MapNodeLabelSource> {
  const m = new Map<string, MapNodeLabelSource>()
  for (const n of nodes) {
    const payload: MapNodeLabelSource = {
      planet: n.planet,
      ownerName: n.ownerName ?? null,
      mapX: Number(n.x),
      mapY: Number(n.y),
    }
    m.set(n.id, payload)
  }
  return m
}

/** Flow-space center of the planet dot; must match `toFlowNodes` + half offset. */
function flowCenterFromMapNode(mapNode: { x: number; y: number }): { cx: number; cy: number } {
  const x = Number(mapNode.x)
  const y = Number(mapNode.y)
  const px = Number.isFinite(x) ? x : 0
  const py = Number.isFinite(y) ? y : 0
  const cx = px + CELL_CENTER_OFFSET
  const cy = gameMapYToFlowCenterY(py)
  return { cx, cy }
}

function FixedSizeDotsOverlay({
  planetGrid,
  planetLabelOptions,
  labelSourceByNodeId,
  mapNodes,
  routeWaypoints,
  waypointGrid,
  onPlanetLabelHoverActiveChange,
}: {
  planetGrid: PlanetSpatialGrid | null
  planetLabelOptions: PlanetLabelOptions
  labelSourceByNodeId: Map<string, MapNodeLabelSource>
  mapNodes: CombinedMapData['nodes']
  routeWaypoints: readonly RouteMapWaypoint[]
  /** Sub-linear hover: same map-cell + radius model as :func:`buildPlanetSpatialGrid` for planets. */
  waypointGrid: PlanetSpatialGrid | null
  onPlanetLabelHoverActiveChange?: (active: boolean) => void
}) {
  const domNode = useStore((s) => s.domNode ?? null)
  const transform = useStore((s) => s.transform)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)
  const [hoveredWaypointId, setHoveredWaypointId] = useState<string | null>(null)
  const [pinnedNodeId, setPinnedNodeId] = useState<string | null>(null)
  const hoverRafRef = useRef<number | null>(null)
  const pendingClientRef = useRef<{ x: number; y: number } | null>(null)
  const lastProcessedClientRef = useRef<{ x: number; y: number } | null>(null)
  const transformRef = useRef(transform)
  const pinnedNodeIdRef = useRef<string | null>(null)
  useLayoutEffect(() => {
    transformRef.current = transform
  }, [transform])
  useLayoutEffect(() => {
    pinnedNodeIdRef.current = pinnedNodeId
  }, [pinnedNodeId])

  const showAnyLabelOption = planetLabelOptionsShowAnyLabel(planetLabelOptions)

  const planetLabelHoverActive =
    pinnedNodeId != null || (showAnyLabelOption && hoveredNodeId != null)

  useEffect(() => {
    onPlanetLabelHoverActiveChange?.(planetLabelHoverActive)
  }, [onPlanetLabelHoverActiveChange, planetLabelHoverActive])

  const mapNodeIdsKey = useMemo(() => mapNodes.map((n) => n.id).join('\0'), [mapNodes])

  useEffect(() => {
    setPinnedNodeId(null)
  }, [mapNodeIdsKey])

  useEffect(() => {
    if (!showAnyLabelOption) {
      setPinnedNodeId(null)
    }
  }, [showAnyLabelOption])

  useEffect(() => {
    if (pinnedNodeId == null) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setPinnedNodeId(null)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [pinnedNodeId])

  useEffect(() => {
    if (pinnedNodeId != null) {
      setHoveredNodeId(null)
      setHoveredWaypointId(null)
    }
  }, [pinnedNodeId])

  const routeWaypointIdSet = useMemo(
    () => new Set(routeWaypoints.map((w) => w.id)),
    [routeWaypoints]
  )
  const hoveredWaypointInList =
    hoveredWaypointId != null && routeWaypointIdSet.has(hoveredWaypointId)
  const hoveredWaypointIdForLabel =
    pinnedNodeId == null && hoveredWaypointInList ? hoveredWaypointId : null

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

  useEffect(() => {
    const el = domNode
    if (!el || size.width <= 0 || size.height <= 0) return

    if (!planetGrid && !waypointGrid) {
      return
    }

    const runHitTest = (clientX: number, clientY: number) => {
      if (pinnedNodeIdRef.current != null) return
      const t = transformRef.current
      if (!t) {
        setHoveredNodeId(null)
        setHoveredWaypointId(null)
        return
      }
      const paneRect = el.getBoundingClientRect()
      const flow = clientToFlowPosition(clientX, clientY, el, t, paneRect)
      if (!flow) {
        setHoveredNodeId(null)
        setHoveredWaypointId(null)
        return
      }
      const rawScale = t[2]
      const scale = safeZoomScale(rawScale)
      const radiusFlow = PLANET_LABEL_HOVER_RADIUS_PX / scale
      if (planetGrid) {
        const { px, py } = flowCenterToPlanet(flow.x, flow.y)
        const closestId = findClosestPlanetWithinRadius(planetGrid, px, py, radiusFlow)
        if (closestId != null) {
          setHoveredNodeId(closestId)
          setHoveredWaypointId(null)
          return
        }
      }
      setHoveredNodeId(null)
      if (waypointGrid) {
        const { px, py } = flowCenterToPlanet(flow.x, flow.y)
        setHoveredWaypointId(findClosestPlanetWithinRadius(waypointGrid, px, py, radiusFlow))
      } else {
        setHoveredWaypointId(null)
      }
    }

    const flushHover = () => {
      const p = pendingClientRef.current
      if (!p) return
      const last = lastProcessedClientRef.current
      if (
        last &&
        Math.abs(p.x - last.x) < HOVER_CLIENT_MOVE_EPS_PX &&
        Math.abs(p.y - last.y) < HOVER_CLIENT_MOVE_EPS_PX
      ) {
        return
      }
      lastProcessedClientRef.current = { x: p.x, y: p.y }
      runHitTest(p.x, p.y)
    }

    const onMove = (e: MouseEvent) => {
      pendingClientRef.current = { x: e.clientX, y: e.clientY }
      if (hoverRafRef.current != null) return
      hoverRafRef.current = requestAnimationFrame(() => {
        hoverRafRef.current = null
        flushHover()
      })
    }
    const onLeave = () => {
      pendingClientRef.current = null
      lastProcessedClientRef.current = null
      if (hoverRafRef.current != null) {
        cancelAnimationFrame(hoverRafRef.current)
        hoverRafRef.current = null
      }
      setHoveredNodeId(null)
      setHoveredWaypointId(null)
    }
    el.addEventListener('mousemove', onMove)
    el.addEventListener('mouseleave', onLeave)
    return () => {
      if (hoverRafRef.current != null) cancelAnimationFrame(hoverRafRef.current)
      hoverRafRef.current = null
      el.removeEventListener('mousemove', onMove)
      el.removeEventListener('mouseleave', onLeave)
    }
  }, [domNode, size.width, size.height, planetGrid, waypointGrid])

  useEffect(() => {
    const el = domNode
    if (!el || !planetGrid) return

    const onClick = (e: MouseEvent) => {
      if (e.button !== 0) return
      const t = transformRef.current
      if (!t) return
      const paneRect = el.getBoundingClientRect()
      const flow = clientToFlowPosition(e.clientX, e.clientY, el, t, paneRect)
      if (!flow) return
      const rawScale = t[2]
      const scale = safeZoomScale(rawScale)
      const radiusPlanet = PLANET_LABEL_HOVER_RADIUS_PX / scale
      const { px, py } = flowCenterToPlanet(flow.x, flow.y)
      const closestId = findClosestPlanetWithinRadius(planetGrid, px, py, radiusPlanet)
      if (closestId == null) {
        if (pinnedNodeIdRef.current != null) {
          setPinnedNodeId(null)
        }
        return
      }
      if (!showAnyLabelOption) {
        if (pinnedNodeIdRef.current != null) {
          setPinnedNodeId(null)
        }
        return
      }
      setPinnedNodeId((prev) => {
        if (prev === closestId) return null
        return closestId
      })
    }
    el.addEventListener('click', onClick)
    return () => el.removeEventListener('click', onClick)
  }, [domNode, planetGrid, showAnyLabelOption])

  if (!transform || size.width <= 0 || size.height <= 0) return null
  const [tx, ty, rawScale] = transform
  const scale = safeZoomScale(rawScale)
  const hoveredForDisplay = planetGrid ? hoveredNodeId : null

  const LABEL_OFFSET_X_PX = 9
  const LABEL_OFFSET_Y_PX = -12

  /**
   * Dots and labels must not share one per-planet stacking group: later planets' dots were painting
   * above earlier planets' labels (same z-index, DOM order), which looked like map bleed-through.
   */
  return (
    <div
      className="pointer-events-none absolute inset-0 z-[5]"
      aria-hidden={pinnedNodeId == null ? true : undefined}
    >
      <div className="absolute inset-0" aria-hidden>
        {routeWaypoints.map((w) => {
          const { cx, cy } = flowCenterFromMapNode({ x: w.gx, y: w.gy })
          const paneX = cx * scale + tx
          const paneY = cy * scale + ty
          const s = ROUTE_WAYPOINT_CROSS_PX
          return (
            <div
              key={w.id}
              className="absolute text-gray-500/75"
              style={{
                left: Math.round(paneX - s / 2),
                top: Math.round(paneY - s / 2),
                width: s,
                height: s,
              }}
            >
              <svg viewBox="0 0 8 8" className="h-full w-full" aria-hidden>
                <line x1="1" y1="1" x2="7" y2="7" stroke="currentColor" strokeWidth="1.1" />
                <line x1="7" y1="1" x2="1" y2="7" stroke="currentColor" strokeWidth="1.1" />
              </svg>
            </div>
          )
        })}
      </div>
      <div className="absolute inset-0" aria-hidden>
        {mapNodes.map((mapNode) => {
          const { cx, cy } = flowCenterFromMapNode(mapNode)
          const paneX = cx * scale + tx
          const paneY = cy * scale + ty
          return (
            <div
              key={`dot-${mapNode.id}`}
              className="absolute rounded-full bg-[#9ca3af]"
              style={{
                left: Math.round(paneX - DOT_PIXELS / 2),
                top: Math.round(paneY - DOT_PIXELS / 2),
                width: DOT_PIXELS,
                height: DOT_PIXELS,
              }}
            />
          )
        })}
      </div>
      <div className="absolute inset-0 z-[1]">
        {routeWaypoints.map((w) => {
          if (hoveredWaypointIdForLabel !== w.id) return null
          const { cx, cy } = flowCenterFromMapNode({ x: w.gx, y: w.gy })
          const paneX = cx * scale + tx
          const paneY = cy * scale + ty
          return (
            <div
              key={`wpl-${w.id}`}
              className="absolute font-mono text-gray-400"
              style={{
                left: Math.round(paneX - DOT_PIXELS / 2 + LABEL_OFFSET_X_PX),
                top: Math.round(paneY - DOT_PIXELS / 2 + LABEL_OFFSET_Y_PX),
                fontSize: 10,
                backgroundColor: '#000000',
                borderRadius: 6,
                padding: '0 4px',
              }}
            >
              {w.gx}, {w.gy}
            </div>
          )
        })}
        {mapNodes.map((mapNode) => {
          const { cx, cy } = flowCenterFromMapNode(mapNode)
          const paneX = cx * scale + tx
          const paneY = cy * scale + ty
          const labelSrc = labelSourceByNodeId.get(mapNode.id)
          const coordX =
            labelSrc != null && Number.isFinite(labelSrc.mapX) ? labelSrc.mapX : Number(mapNode.x)
          const coordY =
            labelSrc != null && Number.isFinite(labelSrc.mapY) ? labelSrc.mapY : Number(mapNode.y)
          const isPinned = pinnedNodeId === mapNode.id
          const showHoverLabel =
            pinnedNodeId == null && showAnyLabelOption && hoveredForDisplay === mapNode.id
          const showLabel = isPinned || showHoverLabel
          if (!showLabel) return null
          return (
            <div
              key={`label-${mapNode.id}`}
              className={cn(
                'absolute font-mono text-gray-300',
                isPinned && 'pointer-events-auto z-[2]'
              )}
              style={{
                left: Math.round(paneX - DOT_PIXELS / 2 + LABEL_OFFSET_X_PX),
                top: Math.round(paneY - DOT_PIXELS / 2 + LABEL_OFFSET_Y_PX),
                fontSize: 10,
                backgroundColor: '#000000',
                borderRadius: 6,
              }}
              onClick={isPinned ? (e) => e.stopPropagation() : undefined}
            >
              <PlanetMapLabel
                options={planetLabelOptions}
                nodeId={mapNode.id}
                planet={labelSrc?.planet}
                ownerName={labelSrc?.ownerName}
                planetX={coordX}
                planetY={coordY}
              />
            </div>
          )
        })}
      </div>
    </div>
  )
}

type MapGraphProps = {
  data: CombinedMapData
  className?: string
  onMapZoomChange: (zoom: number) => void
  /** Called once so the header slider can drive zoom (same as scroll wheel). */
  onSetZoomReady: (setZoom: (zoom: number) => void) => void
  planetLabelOptions?: PlanetLabelOptions
  analyticScope?: AnalyticShellScope | null
  stellarCartographySampleEnabled?: boolean
  cartographyLayerVisibility?: CartographyLayerVisibility
  cartographySettingsGates?: StellarCartographySettingsGates
  wormholeDisplayMode?: WormholeDisplayMode
}

/** Mirrors React Flow zoom to the app (wheel, pinch, initial fit, slider). */
function ViewportZoomSync({ onMapZoomChange }: { onMapZoomChange: (z: number) => void }) {
  const raw = useStore((s) => s.transform?.[2])
  const zoom = Number.isFinite(raw) && (raw as number) > 0 ? (raw as number) : 1
  const prev = useRef(zoom)
  const rafRef = useRef<number | null>(null)
  const pendingZoomRef = useRef<number>(zoom)
  useEffect(() => {
    if (Math.abs(prev.current - zoom) < 1e-9) return
    prev.current = zoom
    pendingZoomRef.current = zoom
    if (rafRef.current != null) return
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null
      onMapZoomChange(pendingZoomRef.current)
    })
  }, [zoom, onMapZoomChange])
  useEffect(() => {
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
    }
  }, [])
  return null
}

/**
 * Registers setZoom(z) so the header slider can set viewport zoom while keeping the view center fixed.
 */
function SliderZoomControl({
  onMapZoomChange,
  onSetZoomReady,
}: {
  onMapZoomChange: (z: number) => void
  onSetZoomReady: (setZoom: (z: number) => void) => void
}) {
  const { getViewport, setViewport } = useReactFlow()
  const storeApi = useStoreApi()
  useEffect(() => {
    const setZoom = (targetZoom: number) => {
      const z = Math.min(40, Math.max(0.2, Number(targetZoom) || 0.2))
      const apply = () => {
        const domNode = storeApi.getState().domNode
        if (!domNode || domNode.getBoundingClientRect().width <= 0) return false
        const vp = getViewport()
        const rect = domNode.getBoundingClientRect()
        const w = Math.max(rect.width, 1)
        const h = Math.max(rect.height, 1)
        const vz = Math.max(Number(vp.zoom) || 0.2, 0.2)
        const vx = Number.isFinite(vp.x) ? vp.x : 0
        const vy = Number.isFinite(vp.y) ? vp.y : 0
        const cx = (w / 2 - vx) / vz
        const cy = (h / 2 - vy) / vz
        const nx = w / 2 - cx * z
        const ny = h / 2 - cy * z
        if (!Number.isFinite(nx) || !Number.isFinite(ny)) return false
        setViewport({ x: nx, y: ny, zoom: z })
        onMapZoomChange(z)
        return true
      }
      if (apply()) return
      let n = 0
      const tick = () => {
        if (apply()) return
        if (++n >= 30) return
        requestAnimationFrame(tick)
      }
      requestAnimationFrame(tick)
    }
    onSetZoomReady(setZoom)
  }, [getViewport, setViewport, storeApi, onMapZoomChange, onSetZoomReady])
  return null
}

/** Max time to wait for initial viewport fit before showing the map anyway (avoids staying invisible if fit never runs). */
const INITIAL_FIT_REVEAL_MS = 250

export function MapGraph({
  data,
  className,
  onMapZoomChange,
  onSetZoomReady,
  planetLabelOptions = DEFAULT_PLANET_LABEL_OPTIONS,
  analyticScope = null,
  stellarCartographySampleEnabled = false,
  cartographyLayerVisibility,
  cartographySettingsGates,
  wormholeDisplayMode = 'always',
}: MapGraphProps) {
  const [initialFitDone, setInitialFitDone] = useState(false)
  const [wormholeHoverLines, setWormholeHoverLines] = useState<string[] | null>(null)
  const [wormholeRecenterPulseTarget, setWormholeRecenterPulseTarget] =
    useState<WormholeRecenterPulseTarget | null>(null)
  const [wormholeLineRevealKey, setWormholeLineRevealKey] = useState<string | null>(null)
  const wormholeLineRevealClearRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [planetLabelHoverActive, setPlanetLabelHoverActive] = useState(false)

  const wormholeLineReveal = useMemo<WormholeLineRevealApi>(
    () => ({
      revealAt: (mapX, mapY) => {
        if (wormholeLineRevealClearRef.current != null) {
          clearTimeout(wormholeLineRevealClearRef.current)
          wormholeLineRevealClearRef.current = null
        }
        setWormholeLineRevealKey(wormholeMapCellKey(mapX, mapY))
      },
      scheduleClear: () => {
        if (wormholeLineRevealClearRef.current != null) {
          clearTimeout(wormholeLineRevealClearRef.current)
        }
        wormholeLineRevealClearRef.current = setTimeout(() => {
          wormholeLineRevealClearRef.current = null
          setWormholeLineRevealKey(null)
        }, WORMHOLE_LINE_REVEAL_CLEAR_MS)
      },
      cancelClear: () => {
        if (wormholeLineRevealClearRef.current != null) {
          clearTimeout(wormholeLineRevealClearRef.current)
          wormholeLineRevealClearRef.current = null
        }
      },
    }),
    []
  )

  useEffect(() => {
    return () => {
      if (wormholeLineRevealClearRef.current != null) {
        clearTimeout(wormholeLineRevealClearRef.current)
      }
    }
  }, [])

  const pulseWormholeAt = useCallback((mapX: number, mapY: number) => {
    setWormholeRecenterPulseTarget({ mapX, mapY, token: Date.now() })
  }, [])

  useEffect(() => {
    if (wormholeRecenterPulseTarget == null) return
    const t = setTimeout(() => setWormholeRecenterPulseTarget(null), WORMHOLE_RECENTER_PULSE_MS)
    return () => clearTimeout(t)
  }, [wormholeRecenterPulseTarget])

  const onPlanetLabelHoverActiveChange = useCallback((active: boolean) => {
    setPlanetLabelHoverActive(active)
    if (active) setWormholeHoverLines(null)
  }, [])

  const onInitialFitDone = useCallback(() => setInitialFitDone(true), [])

  useEffect(() => {
    const t = setTimeout(() => setInitialFitDone(true), INITIAL_FIT_REVEAL_MS)
    return () => clearTimeout(t)
  }, [])

  const nodes = useMemo(() => toFlowNodes(data.nodes), [data.nodes])
  const visibleMapEdges = useMemo(
    () =>
      filterWormholeEdgesForDisplayMode(
        data.edges,
        wormholeDisplayMode,
        wormholeLineRevealKey
      ),
    [data.edges, wormholeDisplayMode, wormholeLineRevealKey]
  )
  const edges = useMemo(() => toEdges(visibleMapEdges), [visibleMapEdges])
  const planetMapNodes = useMemo(
    () => data.nodes.filter((n) => n.planet != null),
    [data.nodes]
  )
  const planetGrid = useMemo(() => buildPlanetSpatialGrid(planetMapNodes), [planetMapNodes])
  const waypointGrid = useMemo(() => {
    const wps = data.routeWaypoints
    if (wps.length === 0) return null
    return buildPlanetSpatialGrid(wps.map((w) => ({ id: w.id, x: w.gx, y: w.gy })))
  }, [data.routeWaypoints])
  const labelSourceByNodeId = useMemo(
    () => buildLabelSourceByNodeId(planetMapNodes),
    [planetMapNodes]
  )
  const wormholeEndpoints = useMemo(
    () => collectWormholeEndpoints(data.nodes, data.wormholeUnknownEntrances),
    [data.nodes, data.wormholeUnknownEntrances]
  )
  const wormholeEndpointHoverByCell = useMemo(
    () => buildWormholeEndpointHoverIndex(data.edges, data.wormholeUnknownEntrances),
    [data.edges, data.wormholeUnknownEntrances]
  )

  return (
    <div
      className={`map-graph-cursor-default relative min-h-0 overflow-hidden bg-black ${className ?? 'h-[320px] w-full min-w-0'}`}
    >
      <div
        className="h-full w-full transition-opacity duration-150"
        style={{ opacity: initialFitDone ? 1 : 0 }}
      >
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          defaultViewport={{ x: 0, y: 0, zoom: 1 }}
          fitView={false}
          minZoom={0.2}
          maxZoom={40}
          proOptions={{ hideAttribution: true }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          panOnDrag
          zoomOnScroll
          zoomOnPinch
        >
          <WormholeHoverContext.Provider value={setWormholeHoverLines}>
            <WormholeLineRevealContext.Provider value={wormholeLineReveal}>
            <WormholeRecenterPulseContext.Provider value={pulseWormholeAt}>
            <InitialViewportFit
              nodes={data.nodes}
              onInitialFitDone={onInitialFitDone}
              onMapZoomChange={onMapZoomChange}
            />
            <ViewportZoomSync onMapZoomChange={onMapZoomChange} />
            <SliderZoomControl onMapZoomChange={onMapZoomChange} onSetZoomReady={onSetZoomReady} />
            <CoordinateGridOverlay />
            <StellarCartographyOverlay
              overlayCircles={data.overlayCircles}
              wormholeEndpoints={wormholeEndpoints}
              wormholeEndpointHoverByCell={wormholeEndpointHoverByCell}
              wormholeRecenterPulseTarget={wormholeRecenterPulseTarget}
              blockedByPlanetHover={planetLabelHoverActive}
              nuIonStorms={data.nuIonStorms}
            />
            <NormalWarpWellOutlinesOverlay mapNodes={planetMapNodes} />
            <FixedSizeDotsOverlay
              planetGrid={planetGrid}
              planetLabelOptions={planetLabelOptions}
              labelSourceByNodeId={labelSourceByNodeId}
              mapNodes={planetMapNodes}
              routeWaypoints={data.routeWaypoints}
              waypointGrid={waypointGrid}
              onPlanetLabelHoverActiveChange={onPlanetLabelHoverActiveChange}
            />
            <FlowCoordinateReadout />
            {cartographyLayerVisibility != null && cartographySettingsGates != null ? (
              <StellarCartographyHoverPanel
                analyticScope={analyticScope}
                sampleEnabled={stellarCartographySampleEnabled}
                layerVisibility={cartographyLayerVisibility}
                settingsGates={cartographySettingsGates}
                wormholeDisplayMode={wormholeDisplayMode}
                wormholeHoverLines={wormholeHoverLines}
                blockedByPlanetHover={planetLabelHoverActive}
                clientToFlowPosition={clientToFlowPosition}
              />
            ) : null}
            </WormholeRecenterPulseContext.Provider>
            </WormholeLineRevealContext.Provider>
          </WormholeHoverContext.Provider>
        </ReactFlow>
      </div>
    </div>
  )
}
