import { useId } from 'react'
import { useStore } from '@xyflow/react'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { buildMapRegionOverlayPaneShapes } from '../../lib/mapRegionOverlay'
import { safeZoomScale } from './geometry'
import { useOverlayPaneSize } from './useOverlayPaneSize'

/**
 * Blit hybrid map region overlays.
 *
 * Disks: opaque SVG circles under one group opacity (union, no stacked alpha).
 * Patches: cached map-space PNGs, reprojected only. Patch AABBs are punched from
 * the disk mask so disks and patches never double-paint.
 */
export function MapRegionOverlayPane({
  regionOverlays,
}: {
  regionOverlays: readonly MapRegionOverlay[]
}) {
  const domNode = useStore((s) => s.domNode ?? null)
  const transform = useStore((s) => s.transform)
  const { width, height } = useOverlayPaneSize(domNode)
  const reactId = useId()
  const idPrefix = `map-region-${reactId.replace(/:/g, '')}`

  if (!transform || width <= 0 || height <= 0) return null
  if (regionOverlays.length === 0) return null

  const [tx, ty, rawScale] = transform
  const scale = safeZoomScale(rawScale)
  const { groups } = buildMapRegionOverlayPaneShapes(regionOverlays, {
    width,
    height,
    tx,
    ty,
    scale,
  })
  if (groups.length === 0) return null

  return (
    <div className="pointer-events-none absolute inset-0 z-[6]" aria-hidden>
      <svg className="h-full w-full" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        <defs>
          {groups.map((group) => {
            if (group.disks.length === 0) return null
            const maskId = `${idPrefix}-disks-${group.key}`
            return (
              <mask
                key={maskId}
                id={maskId}
                maskUnits="userSpaceOnUse"
                x={0}
                y={0}
                width={width}
                height={height}
              >
                <rect x={0} y={0} width={width} height={height} fill="black" />
                {group.disks.map((disk) => (
                  <circle
                    key={disk.key}
                    cx={disk.cx}
                    cy={disk.cy}
                    r={disk.r}
                    fill="white"
                  />
                ))}
                {group.patchMaskRects.map((rect, i) => (
                  <rect
                    key={`${group.key}-punch-${i}`}
                    x={rect.x}
                    y={rect.y}
                    width={rect.width}
                    height={rect.height}
                    fill="black"
                  />
                ))}
              </mask>
            )
          })}
        </defs>
        {groups.map((group) => {
          const maskId = `${idPrefix}-disks-${group.key}`
          return (
            <g key={group.key} opacity={group.fillOpacity}>
              {group.disks.length > 0 ? (
                <rect
                  x={0}
                  y={0}
                  width={width}
                  height={height}
                  fill={group.fillColor}
                  mask={`url(#${maskId})`}
                />
              ) : null}
              {group.patches.map((patch) => (
                <image
                  key={patch.key}
                  href={patch.imageDataUrl}
                  x={patch.left}
                  y={patch.top}
                  width={patch.width}
                  height={patch.height}
                  preserveAspectRatio="none"
                />
              ))}
            </g>
          )
        })}
      </svg>
    </div>
  )
}
