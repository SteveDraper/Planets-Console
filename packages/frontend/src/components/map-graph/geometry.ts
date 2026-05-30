import { PLANET_CELL_CENTER_OFFSET } from '../../lib/planetSpatialGrid'

/** Stable node size in flow space so React Flow keeps node measurements through zoom. */
export const NODE_SIZE_FLOW = 12

/** Offset so node and edge targets use the center of the map cell (0.5, 0.5) as demarcated by grid lines at integers. */
export const CELL_CENTER_OFFSET = PLANET_CELL_CENTER_OFFSET

export function safeZoomScale(scale: number | undefined): number {
  return typeof scale === 'number' && Number.isFinite(scale) && scale > 0 ? scale : 1
}

/** Flow Y for React Flow (y grows downward); smaller game y sits lower on screen. */
export function gameMapYToFlowCenterY(py: number): number {
  return -(py + CELL_CENTER_OFFSET)
}

/** Flow-space center of the planet dot; must match `toFlowNodes` + half offset. */
export function flowCenterFromMapNode(mapNode: { x: number; y: number }): {
  cx: number
  cy: number
} {
  const x = Number(mapNode.x)
  const y = Number(mapNode.y)
  const px = Number.isFinite(x) ? x : 0
  const py = Number.isFinite(y) ? y : 0
  const cx = px + CELL_CENTER_OFFSET
  const cy = gameMapYToFlowCenterY(py)
  return { cx, cy }
}

/**
 * Converts client position to flow (graph) coordinates.
 * xyflow stores transform as [tx, ty, scale] where flow = (pane - translation) / scale.
 */
export function clientToFlowPosition(
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

export function recenterViewportOnFlowPoint(
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
