import { createContext, type CSSProperties, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import {
  BaseEdge,
  getStraightPath,
  ReactFlow,
  Background,
  Handle,
  Panel,
  Position,
  useStore,
  type Node,
  type Edge,
  type EdgeProps,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { CombinedMapData } from '../api/bff'

type DotNodeData = {
  label?: string
  ordinal: number
  x: number
  y: number
}

/** Fixed pixel size of the planet dot on screen (independent of zoom). */
const DOT_PIXELS = 8
/** Minimum node size in flow space so nodes don't vanish at very high zoom. */
const MIN_NODE_SIZE_FLOW = 0.5
/** Minimum edge stroke in flow space so edges don't vanish at very high zoom. */
const MIN_STROKE_FLOW = 0.05
/** Offset so node and edge targets use the center of the map cell (0.5, 0.5) as demarcated by grid lines at integers. */
const CELL_CENTER_OFFSET = 0.5

/** Invisible handle at node center so edges connect to dot center. */
const centerHandleStyle: CSSProperties = {
  position: 'absolute',
  top: '50%',
  left: '50%',
  transform: 'translate(-50%, -50%)',
  opacity: 0,
  width: 1,
  height: 1,
  minWidth: 1,
  minHeight: 1,
  border: 'none',
  padding: 0,
}

/** Dot plus label. Node wrapper is exactly dotSizeFlow so bbox center = (px,py). Dot is drawn by FixedSizeDotsOverlay (always 8px); this node only provides layout and label. Read-only. */
function DotNode(props: NodeProps<Node<DotNodeData>>) {
  const d = props.data
  const scale = useStore((s) => s.transform?.[2] ?? 1)
  const label = d?.label ?? ''
  const x = typeof d?.x === 'number' && Number.isFinite(d.x) ? d.x : '?'
  const y = typeof d?.y === 'number' && Number.isFinite(d.y) ? d.y : '?'
  const s = Math.max(scale, 0.1)
  const dotSizeFlow = Math.max(DOT_PIXELS / s, MIN_NODE_SIZE_FLOW)
  return (
    <div
      className="relative"
      style={{ width: dotSizeFlow, height: dotSizeFlow, minWidth: dotSizeFlow, minHeight: dotSizeFlow }}
    >
      <Handle type="target" position={Position.Left} id="t" style={centerHandleStyle} />
      <Handle type="source" position={Position.Left} id="s" style={centerHandleStyle} />
      <span
        className="absolute left-full top-1/2 -translate-y-1/2 whitespace-nowrap pl-1 font-mono text-gray-300"
        style={{ fontSize: 10 / s }}
      >
        {label} ({String(x)},{String(y)})
      </span>
    </div>
  )
}

const nodeTypes = { dot: DotNode }

/** Map coordinates (px, py) are cell indices; we place the dot at the center of the cell (px + 0.5, py + 0.5) so edges and dot align at high zoom. */
function toFlowNodes(nodes: CombinedMapData['nodes'], scale: number): Node<DotNodeData>[] {
  const s = Math.max(scale, 0.1)
  const half = Math.max(DOT_PIXELS / 2 / s, MIN_NODE_SIZE_FLOW / 2)
  return nodes.map((node, i) => {
    const x = Number(node.x)
    const y = Number(node.y)
    const px = Number.isFinite(x) ? x : 0
    const py = Number.isFinite(y) ? y : 0
    const cx = px + CELL_CENTER_OFFSET
    const cy = py + CELL_CENTER_OFFSET
    return {
      id: node.id,
      type: 'dot',
      position: { x: cx - half, y: cy - half },
      data: { label: node.label, ordinal: i + 1, x: px, y: py },
    }
  })
}

const EDGE_STROKE = '#9ca3af'

/** Straight edge from node center to node center; use node position + half size (same as layout) so edge aligns to cell center. 1px stroke at any zoom. */
function StraightEdgeOnePixel(props: EdgeProps) {
  const {
    source,
    target,
    style,
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition: _sp,
    targetPosition: _tp,
    sourceHandleId: _sh,
    targetHandleId: _th,
    pathOptions: _po,
    selectable: _sel,
    deletable: _del,
    ...rest
  } = props
  const scale = useStore((s) => s.transform?.[2] ?? 1)
  const storeState = useStore((s) => s) as { nodeLookup?: Map<string, Node>; nodeInternals?: Map<string, Node> }
  const nodeLookup = storeState.nodeLookup ?? storeState.nodeInternals
  const sourceNode = nodeLookup?.get(source) as Node<DotNodeData> | undefined
  const targetNode = nodeLookup?.get(target) as Node<DotNodeData> | undefined
  const s = Math.max(scale, 0.1)
  const half = Math.max(DOT_PIXELS / 2 / s, MIN_NODE_SIZE_FLOW / 2)
  const sx =
    sourceNode?.position != null
      ? sourceNode.position.x + half
      : typeof sourceNode?.data?.x === 'number'
        ? sourceNode.data.x + CELL_CENTER_OFFSET
        : sourceX
  const sy =
    sourceNode?.position != null
      ? sourceNode.position.y + half
      : typeof sourceNode?.data?.y === 'number'
        ? sourceNode.data.y + CELL_CENTER_OFFSET
        : sourceY
  const tx =
    targetNode?.position != null
      ? targetNode.position.x + half
      : typeof targetNode?.data?.x === 'number'
        ? targetNode.data.x + CELL_CENTER_OFFSET
        : targetX
  const ty =
    targetNode?.position != null
      ? targetNode.position.y + half
      : typeof targetNode?.data?.y === 'number'
        ? targetNode.data.y + CELL_CENTER_OFFSET
        : targetY
  const [path, labelX, labelY] = getStraightPath({
    sourceX: sx,
    sourceY: sy,
    targetX: tx,
    targetY: ty,
  })
  const strokeWidth = Math.max(1 / Math.max(scale, 0.1), MIN_STROKE_FLOW)
  return (
    <BaseEdge
      path={path}
      labelX={labelX}
      labelY={labelY}
      style={{
        ...style,
        stroke: EDGE_STROKE,
        strokeWidth,
      }}
      {...rest}
    />
  )
}

const edgeTypes = { straight: StraightEdgeOnePixel }

function toEdges(edges: CombinedMapData['edges']): Edge[] {
  return edges.map((e, i) => ({
    id: `e-${e.source}-${e.target}-${i}`,
    source: e.source,
    target: e.target,
    sourceHandle: 's',
    targetHandle: 't',
    type: 'straight',
  }))
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
  transform: [number, number, number] | undefined
): { x: number; y: number } | null {
  if (!domNode || !transform) return null
  const rect = domNode.getBoundingClientRect()
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
      <>x: {Math.floor(flow.x)} y: {Math.floor(flow.y)} zoom: {scale != null ? scale.toFixed(2) : '—'}</>
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
const GRID_ZOOM_THRESHOLD = 5

/** Solid light grey so crossings don't brighten (no alpha blend). */
const GRID_STROKE = '#6b7280'

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
  const [tx, ty, scale] = transform
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
      className="pointer-events-none absolute inset-0"
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

/**
 * Renders planet dots in screen (pane) space so they are always exactly DOT_PIXELS
 * in size regardless of zoom. Uses same flow→pane conversion as the grid.
 */
function FixedSizeDotsOverlay() {
  const domNode = useStore((s) => s.domNode ?? null)
  const transform = useStore((s) => s.transform)
  const storeState = useStore((s) => s) as unknown as { nodeLookup?: Map<string, { id: string; position: { x: number; y: number } }>; nodeInternals?: Map<string, { id: string; position: { x: number; y: number } }> }
  const nodeLookup = storeState.nodeLookup ?? storeState.nodeInternals
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

  if (!transform || !nodeLookup || size.width <= 0 || size.height <= 0) return null
  const [tx, ty, scale] = transform
  const s = Math.max(scale, 0.1)
  const half = Math.max(DOT_PIXELS / 2 / s, MIN_NODE_SIZE_FLOW / 2)
  const nodes = Array.from(nodeLookup.values())

  return (
    <div className="pointer-events-none absolute inset-0" aria-hidden>
      {nodes.map((node) => {
        const cx = node.position.x + half
        const cy = node.position.y + half
        const paneX = cx * scale + tx
        const paneY = cy * scale + ty
        return (
          <div
            key={node.id}
            className="absolute rounded-full bg-[#9ca3af]"
            style={{
              left: paneX - DOT_PIXELS / 2,
              top: paneY - DOT_PIXELS / 2,
              width: DOT_PIXELS,
              height: DOT_PIXELS,
            }}
          />
        )
      })}
    </div>
  )
}

type MapGraphProps = {
  data: CombinedMapData
  className?: string
}

/** Lifts viewport scale from React Flow store to parent (with optional debounce for position updates). */
const ScaleSyncContext = createContext<((s: number) => void) | null>(null)

function ScaleSync() {
  const onScaleChange = useContext(ScaleSyncContext)
  const scale = useStore((s) => s.transform?.[2] ?? 1)
  useEffect(() => {
    onScaleChange?.(scale)
  }, [scale, onScaleChange])
  return null
}

/** Delay (ms) after zoom stops before we update node positions for correct alignment. */
const POSITION_UPDATE_DELAY_MS = 120

export function MapGraph({ data, className }: MapGraphProps) {
  const [scaleForPositions, setScaleForPositions] = useState(1)
  const delayRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const onScaleChange = useCallback((newScale: number) => {
    if (delayRef.current) clearTimeout(delayRef.current)
    delayRef.current = setTimeout(() => {
      delayRef.current = null
      setScaleForPositions(newScale)
    }, POSITION_UPDATE_DELAY_MS)
  }, [])

  useEffect(() => {
    return () => {
      if (delayRef.current) clearTimeout(delayRef.current)
    }
  }, [])

  const nodes = useMemo(
    () => toFlowNodes(data.nodes, scaleForPositions),
    [data.nodes, scaleForPositions]
  )
  const edges = useMemo(() => toEdges(data.edges), [data.edges])

  return (
    <ScaleSyncContext.Provider value={onScaleChange}>
      <div
        className={`map-graph-cursor-default relative min-h-0 overflow-hidden rounded bg-black ${className ?? 'h-[320px] w-full min-w-0'}`}
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
          <ScaleSync />
          <Background
            gap={16}
            size={1}
            className="!stroke-gray-800"
            color="#1f2937"
          />
          <CoordinateGridOverlay />
          <FixedSizeDotsOverlay />
          <FlowCoordinateReadout />
        </ReactFlow>
      </div>
    </ScaleSyncContext.Provider>
  )
}
