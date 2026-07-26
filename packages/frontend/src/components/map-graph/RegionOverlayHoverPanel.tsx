/**
 * Debounced map tooltip for ``regionOverlays`` with structured hover facts.
 * Hit-tests filtered overlays in continuous map coordinates.
 */

import { useEffect, useState } from 'react'
import { useStore } from '@xyflow/react'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { flowCenterToPlanet } from '../../lib/planetSpatialGrid'
import { collectRegionOverlayHoverSummaries } from '../../lib/mapRegionOverlayHitTest'
import { formatRegionOverlayHoverLine } from './formatRegionOverlayHover'
import { clientToFlowPosition } from './geometry'

type RegionOverlayHoverPanelProps = {
  regionOverlays: readonly MapRegionOverlay[]
  /** When a planet hover/pin label is showing, suppress region hover. */
  blockedByPlanetHover?: boolean
}

export type MapPaneClientPos = { x: number; y: number }

export function regionOverlayHoverLinesAtClient(
  regionOverlays: readonly MapRegionOverlay[],
  clientX: number,
  clientY: number,
  domNode: HTMLElement | null,
  transform: [number, number, number] | undefined
): string[] {
  const flow = clientToFlowPosition(clientX, clientY, domNode, transform)
  if (flow == null) return []
  const { px, py } = flowCenterToPlanet(flow.x, flow.y)
  return collectRegionOverlayHoverSummaries(
    regionOverlays,
    px,
    py,
    formatRegionOverlayHoverLine
  )
}

/**
 * Tracks client pointer over the React Flow pane.
 *
 * Must be called from a component mounted under ``ReactFlow`` (xyflow store).
 */
export function useMapPaneClientPos(): {
  clientPos: MapPaneClientPos | null
  domNode: HTMLElement | null
} {
  const domNode = useStore((s) => s.domNode ?? null)
  const [clientPos, setClientPos] = useState<MapPaneClientPos | null>(null)

  useEffect(() => {
    const el = domNode
    if (!el) {
      setClientPos(null)
      return
    }
    const onMove = (e: MouseEvent) => setClientPos({ x: e.clientX, y: e.clientY })
    const onLeave = () => setClientPos(null)
    el.addEventListener('mousemove', onMove)
    el.addEventListener('mouseleave', onLeave)
    return () => {
      el.removeEventListener('mousemove', onMove)
      el.removeEventListener('mouseleave', onLeave)
    }
  }, [domNode])

  return { clientPos, domNode }
}

/** Live hover lines under the pointer for the given overlays.

Must be called from a component mounted under ``ReactFlow`` (xyflow store).
Returns ``clientPos`` so tooltip chrome can share the same pointer source.
*/
export function useRegionOverlayHoverLines(
  regionOverlays: readonly MapRegionOverlay[],
  blockedByPlanetHover = false
): { lines: string[]; clientPos: MapPaneClientPos | null } {
  const transform = useStore((s) => s.transform)
  const { clientPos, domNode } = useMapPaneClientPos()

  if (blockedByPlanetHover || clientPos == null || regionOverlays.length === 0) {
    return { lines: [], clientPos }
  }
  return {
    lines: regionOverlayHoverLinesAtClient(
      regionOverlays,
      clientPos.x,
      clientPos.y,
      domNode,
      transform
    ),
    clientPos,
  }
}

type RegionOverlayHoverTooltipProps = {
  lines: readonly string[]
  /** Shared pointer from ``useRegionOverlayHoverLines`` / ``useMapPaneClientPos``. */
  clientPos: MapPaneClientPos | null
}

/** Shared stacked tooltip chrome for region overlay hover lines. */
export function RegionOverlayHoverTooltip({
  lines,
  clientPos,
}: RegionOverlayHoverTooltipProps) {
  const domNode = useStore((s) => s.domNode ?? null)

  if (lines.length === 0 || clientPos == null || domNode == null) return null

  const rect = domNode.getBoundingClientRect()
  const paneX = clientPos.x - rect.left + 12
  const paneY = clientPos.y - rect.top - 8

  return (
    <div
      className="pointer-events-none absolute z-[6] max-w-xs font-mono text-xs text-gray-300"
      style={{
        left: paneX,
        top: paneY,
        transform: 'translateY(-100%)',
        backgroundColor: '#000000',
        borderRadius: 6,
        padding: '4px 8px',
      }}
    >
      {lines.map((line, i) => (
        <div key={`${i}-${line}`}>{line}</div>
      ))}
    </div>
  )
}

/**
 * Standalone region hover tooltip (when Stellar Cartography panel is not mounting
 * the stacked tooltip). Prefer feeding lines into cartography when it is enabled.
 *
 * Must render as a descendant of ``ReactFlow`` -- ``useStore`` requires the
 * xyflow provider (https://reactflow.dev/error#001).
 */
export function RegionOverlayHoverPanel({
  regionOverlays,
  blockedByPlanetHover = false,
}: RegionOverlayHoverPanelProps) {
  const { lines, clientPos } = useRegionOverlayHoverLines(
    regionOverlays,
    blockedByPlanetHover
  )
  return <RegionOverlayHoverTooltip lines={lines} clientPos={clientPos} />
}
