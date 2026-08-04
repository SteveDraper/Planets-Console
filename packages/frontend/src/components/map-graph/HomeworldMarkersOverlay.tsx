import { useStore } from '@xyflow/react'
import { homeworldMarkerRings } from '../../analytics/homeworld-locator/homeworldMarkerRingStyle'
import type { HomeworldMapMarkerDisplay } from '../../analytics/homeworld-locator/mapAnalytic'
import { useHomeworldCandidateFlashStore } from '../../stores/homeworldCandidateFlash'
import { useHomeworldLocatorSelectionStore } from '../../stores/homeworldLocatorSelection'
import { flowCenterFromMapNode, safeZoomScale } from './geometry'
import { useOverlayPaneSize } from './useOverlayPaneSize'

/** Outer ring diameter in screen pixels (independent of zoom). */
const MARKER_DIAMETER_PX = 12

/**
 * Homeworld locator planet decorations on the base map.
 * Solid ring = definite; dashed/lighter ring = possible; double dotted = most probable;
 * amber outer ring = asserted cue; cyan halo = panel/table selection;
 * pulse = ephemeral flash after candidate row click.
 */
export function HomeworldMarkersOverlay({
  markers,
}: {
  markers: readonly HomeworldMapMarkerDisplay[]
}) {
  const domNode = useStore((s) => s.domNode ?? null)
  const transform = useStore((s) => s.transform)
  const { width, height } = useOverlayPaneSize(domNode)
  const selection = useHomeworldLocatorSelectionStore((s) => s.selection)
  const flashTarget = useHomeworldCandidateFlashStore((s) => s.flashTarget)

  if (!transform || width <= 0 || height <= 0) return null
  if (markers.length === 0) return null

  const [tx, ty, rawScale] = transform
  const scale = safeZoomScale(rawScale)
  const baseRadius = MARKER_DIAMETER_PX / 2

  return (
    <div className="pointer-events-none absolute inset-0 z-[6]" aria-hidden>
      <svg className="h-full w-full" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        {markers.map((marker) => {
          const { cx, cy } = flowCenterFromMapNode({ x: marker.x, y: marker.y })
          const paneX = cx * scale + tx
          const paneY = cy * scale + ty
          const isSelected =
            selection?.kind === 'planet' && selection.planetId === marker.planetId
          const isFlashing =
            flashTarget != null && flashTarget.planetId === marker.planetId
          const rings = homeworldMarkerRings({
            ...marker,
            isSelected,
          })
          const markerKey = `hw-${marker.planetId}-${marker.perspective ?? 'o'}-${marker.confidenceTier}-${marker.assertedCue ? 'a' : 'n'}-${marker.isMostProbable ? 'mp' : 'n'}`
          return (
            <g
              key={isFlashing ? `${markerKey}-flash-${flashTarget.token}` : markerKey}
              transform={`translate(${paneX} ${paneY})`}
            >
              <g className={isFlashing ? 'wormhole-recenter-pulse' : undefined}>
                {rings.map((ring, ringIndex) => (
                  <circle
                    key={`${markerKey}-${ringIndex}`}
                    cx={0}
                    cy={0}
                    r={baseRadius * ring.radiusScale}
                    fill="none"
                    stroke={ring.stroke}
                    strokeWidth={ring.strokeWidth}
                    strokeDasharray={ring.strokeDasharray}
                    opacity={ring.opacity}
                  />
                ))}
              </g>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
