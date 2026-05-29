import type { MapBounds, MapPoint } from './cartographyOverlayGeometry'

export type ScalarGrid = {
  values: Float32Array
  cols: number
  rows: number
  minX: number
  minY: number
  step: number
}

/** @deprecated Use ScalarGrid */
export type DensityGrid = ScalarGrid

export type ScalarFieldComponent = {
  origin: MapPoint
  maxSearchRadius: number
}

export function buildScalarGrid(
  bounds: MapBounds,
  step: number,
  sampleAt: (mapX: number, mapY: number) => number
): ScalarGrid {
  const cols = Math.max(2, Math.ceil((bounds.maxX - bounds.minX) / step) + 1)
  const rows = Math.max(2, Math.ceil((bounds.maxY - bounds.minY) / step) + 1)
  const values = new Float32Array(cols * rows)
  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      const mapX = bounds.minX + col * step
      const mapY = bounds.minY + row * step
      values[row * cols + col] = sampleAt(mapX, mapY)
    }
  }
  return { values, cols, rows, minX: bounds.minX, minY: bounds.minY, step }
}

export function gridValueAt(grid: ScalarGrid, col: number, row: number): number {
  if (col < 0 || row < 0 || col >= grid.cols || row >= grid.rows) return 0
  return grid.values[row * grid.cols + col] ?? 0
}

export function gridPointToMap(grid: ScalarGrid, col: number, row: number): MapPoint {
  return { x: grid.minX + col * grid.step, y: grid.minY + row * grid.step }
}

function maxSearchRadiusForComponent(
  origin: MapPoint,
  minCol: number,
  maxCol: number,
  minRow: number,
  maxRow: number,
  grid: ScalarGrid
): number {
  const { minX, minY, step } = grid
  let maxDist = step
  for (let col = minCol; col <= maxCol; col += 1) {
    for (let row = minRow; row <= maxRow; row += 1) {
      for (const [dx, dy] of [
        [0, 0],
        [step, 0],
        [0, step],
        [step, step],
      ] as const) {
        const x = minX + col * step + dx
        const y = minY + row * step + dy
        maxDist = Math.max(maxDist, Math.hypot(x - origin.x, y - origin.y))
      }
    }
  }
  return maxDist + step
}

/** Flood-fill connected components; origin is the peak-value cell in each component. */
export function findComponentsInGrid(
  grid: ScalarGrid,
  cellIncluded: (col: number, row: number) => boolean
): ScalarFieldComponent[] {
  const { cols, rows, step, minX, minY } = grid
  const visited = new Uint8Array(cols * rows)
  const components: ScalarFieldComponent[] = []

  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      const index = row * cols + col
      if (visited[index] !== 0 || !cellIncluded(col, row)) continue

      let peakCol = col
      let peakRow = row
      let peakValue = gridValueAt(grid, col, row)
      let minCol = col
      let maxCol = col
      let minRow = row
      let maxRow = row
      const stack: Array<[number, number]> = [[col, row]]
      visited[index] = 1

      while (stack.length > 0) {
        const [currentCol, currentRow] = stack.pop()!
        minCol = Math.min(minCol, currentCol)
        maxCol = Math.max(maxCol, currentCol)
        minRow = Math.min(minRow, currentRow)
        maxRow = Math.max(maxRow, currentRow)

        for (const [deltaCol, deltaRow] of [
          [0, 1],
          [1, 0],
          [0, -1],
          [-1, 0],
        ] as const) {
          const nextCol = currentCol + deltaCol
          const nextRow = currentRow + deltaRow
          if (nextCol < 0 || nextRow < 0 || nextCol >= cols || nextRow >= rows) continue
          const nextIndex = nextRow * cols + nextCol
          if (visited[nextIndex] !== 0 || !cellIncluded(nextCol, nextRow)) continue
          visited[nextIndex] = 1
          stack.push([nextCol, nextRow])
          const nextValue = gridValueAt(grid, nextCol, nextRow)
          if (nextValue > peakValue) {
            peakValue = nextValue
            peakCol = nextCol
            peakRow = nextRow
          }
        }
      }

      const origin = { x: minX + peakCol * step, y: minY + peakRow * step }
      components.push({
        origin,
        maxSearchRadius: maxSearchRadiusForComponent(origin, minCol, maxCol, minRow, maxRow, grid),
      })
    }
  }

  return components
}
