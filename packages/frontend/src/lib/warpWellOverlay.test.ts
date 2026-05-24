import { describe, expect, it } from 'vitest'
import { combineMapData } from '../analytics/mapLayers'
import { normalizeMapDataResponse } from '../api/bff'
import { buildWarpWellOverlayPaneLines, WARP_WELL_OVERLAY_ZOOM_THRESHOLD } from './warpWellOverlay'

/** Minimal 29-cell normal well around `(px, py)`. */
function sampleNormalWellCells(px: number, py: number) {
  const cells: { x: number; y: number }[] = []
  for (let dgx = -3; dgx <= 3; dgx++) {
    for (let dgy = -3; dgy <= 3; dgy++) {
      const gx = px + dgx
      const gy = py + dgy
      if (Math.hypot(gx - px, gy - py) <= 3) {
        cells.push({ x: gx, y: gy })
      }
    }
  }
  return cells
}

/** Viewport centered on a map cell in flow space (matches MapGraph pane math). */
function viewportCenteredOnMapCell(gx: number, gy: number, scale: number) {
  const width = 800
  const height = 600
  const cx = gx + 0.5
  const cy = -(gy + 0.5)
  return {
    width,
    height,
    tx: width / 2 - cx * scale,
    ty: height / 2 - cy * scale,
    scale,
  }
}

describe('warp well overlay regression', () => {
  it('preserves normalWellCells through normalize and combineMapData', () => {
    const cells = sampleNormalWellCells(10, 20)
    expect(cells).toHaveLength(29)

    const raw = {
      analyticId: 'base-map',
      nodes: [
        {
          id: 'p1',
          label: 'p1',
          x: 10,
          y: 20,
          planet: { id: 1, debrisdisk: 0 },
          ownerName: 'player',
          normalWellCells: cells,
        },
      ],
      edges: [],
    }

    const normalized = normalizeMapDataResponse(raw)
    expect(normalized.nodes[0].normalWellCells).toHaveLength(29)

    const combined = combineMapData(['base-map'], [{ data: normalized }], null)
    expect(combined.nodes[0].normalWellCells).toHaveLength(29)
  })

  it('draws overlay lines when zoom is above the warp-well threshold and cells are present', () => {
    const px = 100
    const py = 200
    const cells = sampleNormalWellCells(px, py)
    const mapNodes = [
      {
        id: 'base-map:p1',
        label: 'p1',
        x: px,
        y: py,
        planet: { id: 1, debrisdisk: 0 },
        normalWellCells: cells,
      },
    ]

    const viewport = viewportCenteredOnMapCell(px, py, WARP_WELL_OVERLAY_ZOOM_THRESHOLD)
    const lines = buildWarpWellOverlayPaneLines(
      mapNodes,
      viewport,
      WARP_WELL_OVERLAY_ZOOM_THRESHOLD
    )

    expect(lines.length).toBeGreaterThan(0)
  })

  it('draws no overlay lines when normalWellCells are missing (regression guard)', () => {
    const mapNodes = [
      {
        id: 'base-map:p1',
        label: 'p1',
        x: 100,
        y: 200,
        planet: { id: 1, debrisdisk: 0 },
      },
    ]

    const viewport = viewportCenteredOnMapCell(100, 200, WARP_WELL_OVERLAY_ZOOM_THRESHOLD)
    const lines = buildWarpWellOverlayPaneLines(
      mapNodes,
      viewport,
      WARP_WELL_OVERLAY_ZOOM_THRESHOLD
    )

    expect(lines).toEqual([])
  })
})
