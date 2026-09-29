import { useStore } from '@xyflow/react'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { buildMapRegionOverlayPaneShapes } from '../../lib/mapRegionOverlay'
import { safeZoomScale } from './geometry'
import { mapPaneZClass } from './mapPaneZOrder'
import { useOverlayPaneSize } from './useOverlayPaneSize'

/** Screen-pixel stroke. High opacity so the hovered team's boundary reads over the 0.35 fill. */
const HIGHLIGHT_STROKE_PX = 3
const HIGHLIGHT_STROKE_OPACITY = 1

/**
 * Solid outline of the legend-hovered team's painted regions.
 * The caller passes only those overlays, and only while Team information is enabled.
 */
export function TeamTerritoryHighlightOutline({
  regionOverlays,
}: {
  regionOverlays: readonly MapRegionOverlay[]
}) {
  const domNode = useStore((s) => s.domNode ?? null)
  const transform = useStore((s) => s.transform)
  const { width, height } = useOverlayPaneSize(domNode)

  if (!transform || width <= 0 || height <= 0 || regionOverlays.length === 0) return null

  const [tx, ty, rawScale] = transform
  const scale = safeZoomScale(rawScale)
  const { groups } = buildMapRegionOverlayPaneShapes(regionOverlays, {
    width,
    height,
    tx,
    ty,
    scale,
  })
  const strokes = groups.filter((group) => group.boundaryPath != null)
  if (strokes.length === 0) return null

  return (
    <div
      className={`pointer-events-none absolute inset-0 ${mapPaneZClass('regionOverlays')}`}
      aria-hidden
      data-team-territory-highlight=""
    >
      <svg className="h-full w-full" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        {strokes.map((group) => (
          <path
            key={group.key}
            d={group.boundaryPath}
            fill="none"
            stroke={group.fillColor}
            strokeOpacity={HIGHLIGHT_STROKE_OPACITY}
            strokeWidth={HIGHLIGHT_STROKE_PX}
            strokeLinejoin="round"
          />
        ))}
      </svg>
    </div>
  )
}
