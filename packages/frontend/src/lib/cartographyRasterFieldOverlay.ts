import type { IonStormCloudPaneShape } from './ionStormCloudOverlay'
import type { NebulaCloudPaneShape } from './nebulaCloudOverlay'

export type CartographyRasterFieldStrokePath = {
  pathKey: string
  path: string
  stroke: string
  strokeWidth: number
}

export type CartographyRasterFieldPaneShape = {
  overlayKey: string
  left: number
  top: number
  width: number
  height: number
  imageDataUrl: string
  fillClipPathId: string
  clipPaths: string[]
  strokePaths: CartographyRasterFieldStrokePath[]
}

export function nebulaCloudPaneShapeToRasterField(
  shape: NebulaCloudPaneShape
): CartographyRasterFieldPaneShape {
  const clipPaths = shape.boundaryPath.length > 0 ? [shape.boundaryPath] : []
  const strokePaths =
    shape.boundaryPath.length > 0
      ? [
          {
            pathKey: 'outer',
            path: shape.boundaryPath,
            stroke: shape.stroke,
            strokeWidth: shape.strokeWidth,
          },
        ]
      : []

  return {
    overlayKey: shape.key,
    left: shape.left,
    top: shape.top,
    width: shape.width,
    height: shape.height,
    imageDataUrl: shape.imageDataUrl,
    fillClipPathId: shape.fillClipPathId,
    clipPaths,
    strokePaths,
  }
}

export function ionStormCloudPaneShapeToRasterField(
  shape: IonStormCloudPaneShape
): CartographyRasterFieldPaneShape {
  const strokePaths: CartographyRasterFieldStrokePath[] = [
    ...shape.classBoundaryPaths.map(({ stormClass, path, stroke }, pathIndex) => ({
      pathKey: `class-${stormClass}-${pathIndex}`,
      path,
      stroke,
      strokeWidth: shape.strokeWidth,
    })),
    ...shape.outerBoundaryPaths.map((path, pathIndex) => ({
      pathKey: `outer-${pathIndex}`,
      path,
      stroke: shape.outerStroke,
      strokeWidth: shape.strokeWidth,
    })),
  ]

  return {
    overlayKey: shape.key,
    left: shape.left,
    top: shape.top,
    width: shape.width,
    height: shape.height,
    imageDataUrl: shape.imageDataUrl,
    fillClipPathId: shape.fillClipPathId,
    clipPaths: shape.outerBoundaryPaths,
    strokePaths,
  }
}
