import { useEffect, useState } from 'react'
import { Panel, useStore } from '@xyflow/react'
import { clientToFlowPosition, safeZoomScale } from './geometry'

/** Show grid when zoom >= this (pixels per flow unit). */
const GRID_ZOOM_THRESHOLD = 15

/** Light grey at 30% opacity so the warp-well overlay reads stronger when lines coincide. */
const GRID_STROKE = 'rgba(107, 114, 128, 0.3)'

/**
 * Tracks mouse over the flow viewport and shows position in flow coordinates.
 * Attaches listeners to the store's domNode so we receive events regardless of
 * whether ReactFlow forwards onMouseMove. Must be rendered inside ReactFlow.
 */
export function FlowCoordinateReadout() {
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

/**
 * Coordinate grid overlay when zoomed in. Drawn in pixel space so lines stay 1px at any zoom;
 * flow positions converted to pane pixels via pane = flow * scale + translation.
 */
export function CoordinateGridOverlay() {
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
