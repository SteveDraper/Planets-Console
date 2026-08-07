/**
 * Debounced map tooltip for ``regionOverlays`` with structured hover facts.
 * Hit-tests filtered overlays in continuous map coordinates.
 *
 * Pane pointer ownership is migrating to the **map interaction surface**
 * (``map-interaction/``); ``useMapPaneClientPos`` is re-exported from there.
 */

import { useStore } from '@xyflow/react'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { flowCenterToPlanet } from '../../lib/planetSpatialGrid'
import { collectRegionOverlayHoverSummaries } from '../../lib/mapRegionOverlayHitTest'
import {
  useMapPaneClientPos,
  type MapPaneClientPos,
} from '../../map-interaction/useMapPanePointer'
import { formatRegionOverlayHoverLine } from './formatRegionOverlayHover'
import { clientToFlowPosition } from './geometry'

export type { MapPaneClientPos }
export { useMapPaneClientPos }

type RegionOverlayHoverPanelProps = {
  regionOverlays: readonly MapRegionOverlay[]
  /** When a planet hover/pin label is showing, suppress region hover. */
  blockedByPlanetHover?: boolean
}

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

/** Hover lines for a shared pane pointer (no listener of its own). */
export function computeRegionOverlayHoverLines(
  regionOverlays: readonly MapRegionOverlay[],
  clientPos: MapPaneClientPos | null,
  domNode: HTMLElement | null,
  transform: [number, number, number] | undefined,
  blockedByPlanetHover = false
): string[] {
  if (blockedByPlanetHover || clientPos == null || regionOverlays.length === 0) {
    return []
  }
  return regionOverlayHoverLinesAtClient(
    regionOverlays,
    clientPos.x,
    clientPos.y,
    domNode,
    transform
  )
}

/** Live hover lines under the pointer for the given overlays.

Must be called from a component mounted under ``ReactFlow`` (xyflow store).
Attaches a pane pointer listener; prefer ``useMapPaneClientPos`` +
``computeRegionOverlayHoverLines`` when composing with other hover consumers.
*/
export function useRegionOverlayHoverLines(
  regionOverlays: readonly MapRegionOverlay[],
  blockedByPlanetHover = false
): { lines: string[]; clientPos: MapPaneClientPos | null } {
  const transform = useStore((s) => s.transform)
  const { clientPos, domNode } = useMapPaneClientPos()
  return {
    lines: computeRegionOverlayHoverLines(
      regionOverlays,
      clientPos,
      domNode,
      transform,
      blockedByPlanetHover
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
