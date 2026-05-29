import {
  computeRasterDimensions,
  mapPointFromRasterPixel,
  type MapBounds,
} from './cartographyOverlayGeometry'

export type MapFieldRasterPixel = {
  r: number
  g: number
  b: number
  a: number
}

export type MapFieldRasterResult = {
  imageDataUrl: string
  alpha: Uint8ClampedArray
  rasterW: number
  rasterH: number
  stepX: number
  stepY: number
}

/** Rasterize a scalar map field to a PNG data URL (row 0 = north / bounds.maxY). */
export function rasterizeMapField(
  bounds: MapBounds,
  maxRasterPx: number,
  pixelAt: (mapX: number, mapY: number) => MapFieldRasterPixel
): MapFieldRasterResult | null {
  if (typeof document === 'undefined') return null

  const { rasterW, rasterH, stepX, stepY } = computeRasterDimensions(bounds, maxRasterPx)

  const canvas = document.createElement('canvas')
  canvas.width = rasterW
  canvas.height = rasterH
  const ctx = canvas.getContext('2d')
  if (ctx == null) return null

  const image = ctx.createImageData(rasterW, rasterH)

  for (let py = 0; py < rasterH; py += 1) {
    for (let px = 0; px < rasterW; px += 1) {
      const { mapX, mapY } = mapPointFromRasterPixel(bounds, px, py, stepX, stepY)
      const { r, g, b, a } = pixelAt(mapX, mapY)
      const offset = (py * rasterW + px) * 4
      image.data[offset] = r
      image.data[offset + 1] = g
      image.data[offset + 2] = b
      image.data[offset + 3] = a
    }
  }

  ctx.putImageData(image, 0, 0)
  return {
    imageDataUrl: canvas.toDataURL('image/png'),
    alpha: image.data,
    rasterW,
    rasterH,
    stepX,
    stepY,
  }
}
