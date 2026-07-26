/**
 * Debounced map tooltip for ``regionOverlays`` with ``hoverSummary``.
 * Hit-tests filtered overlays in continuous map coordinates.
 */

import { useEffect, useState } from 'react'
import { useStore } from '@xyflow/react'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { flowCenterToPlanet } from '../../lib/planetSpatialGrid'
import { collectRegionOverlayHoverSummaries } from '../../lib/mapRegionOverlayHitTest'
import { clientToFlowPosition } from './geometry'

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
  return collectRegionOverlayHoverSummaries(regionOverlays, px, py)
}

/** Live ``hoverSummary`` lines under the pointer for the given overlays. */
export function useRegionOverlayHoverLines(
  regionOverlays: readonly MapRegionOverlay[],
  blockedByPlanetHover = false
): string[] {
  const domNode = useStore((s) => s.domNode ?? null)
  const transform = useStore((s) => s.transform)
  const [clientPos, setClientPos] = useState<{ x: number; y: number } | null>(null)

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

type RegionOverlayHoverTooltipProps = {
  lines: readonly string[]
}

/** Shared stacked tooltip chrome for region overlay hover lines. */
export function RegionOverlayHoverTooltip({ lines }: RegionOverlayHoverTooltipProps) {
  const domNode = useStore((s) => s.domNode ?? null)
  const [clientPos, setClientPos] = useState<{ x: number; y: number } | null>(null)

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
 */
export function RegionOverlayHoverPanel({
  regionOverlays,
  blockedByPlanetHover = false,
}: RegionOverlayHoverPanelProps) {
  const lines = useRegionOverlayHoverLines(regionOverlays, blockedByPlanetHover)
  return <RegionOverlayHoverTooltip lines={lines} />
}
