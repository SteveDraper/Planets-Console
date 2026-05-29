import type { CartographyRasterFieldPaneShape } from '../lib/cartographyRasterFieldOverlay'

export type RasterFieldOverlayProps = CartographyRasterFieldPaneShape

export function RasterFieldOverlay({
  overlayKey,
  left,
  top,
  width,
  height,
  imageDataUrl,
  fillClipPathId,
  clipPaths,
  strokePaths,
}: RasterFieldOverlayProps) {
  const clipPathD = clipPaths.filter((path) => path.length > 0).join(' ')

  return (
    <g>
      {clipPathD.length > 0 && (
        <defs>
          <clipPath id={fillClipPathId}>
            <path d={clipPathD} />
          </clipPath>
        </defs>
      )}
      <image
        href={imageDataUrl}
        x={left}
        y={top}
        width={width}
        height={height}
        preserveAspectRatio="none"
        clipPath={clipPathD.length > 0 ? `url(#${fillClipPathId})` : undefined}
      />
      {strokePaths.map(({ pathKey, path, stroke, strokeWidth }) =>
        path.length > 0 ? (
          <path
            key={`${overlayKey}-${pathKey}`}
            d={path}
            fill="none"
            stroke={stroke}
            strokeWidth={strokeWidth}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ) : null
      )}
    </g>
  )
}
