import { describe, expect, it } from 'vitest'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { buildMapRegionOverlayPaneShapes } from '../../lib/mapRegionOverlay'
import { HOMEWORLD_SECTOR_KIND } from './homeworldRegionDisplayMode'
import { applyHomeworldRegionStyle, homeworldSectorPaint } from './homeworldRegionStyle'

function sectorOverlay(overrides: Partial<MapRegionOverlay> = {}): MapRegionOverlay {
  return {
    kind: HOMEWORLD_SECTOR_KIND,
    id: 'homeworld-sector-0',
    fillColor: '#f97316',
    fillOpacity: 0.2,
    geometry: {
      type: 'boundary',
      vertices: [
        { x: 200, y: 0 },
        { x: 0, y: 200 },
        { x: 0, y: 100 },
        { x: 100, y: 0 },
      ],
      edges: [
        { type: 'arc', centerX: 0, centerY: 0, clockwise: false },
        { type: 'line' },
        { type: 'arc', centerX: 0, centerY: 0, clockwise: true },
        { type: 'line' },
      ],
      disks: [
        { x: 150, y: 50, radius: 81 },
        { x: 150, y: 50, radius: 162 },
      ],
    },
    ...overrides,
  }
}

function visibilityOverlay(): MapRegionOverlay {
  return {
    kind: 'ship-scan',
    id: 'vis-1',
    fillColor: '#38bdf8',
    fillOpacity: 0.28,
    geometry: {
      type: 'coverage',
      disks: [{ x: 0, y: 0, radius: 100 }],
      patches: [],
    },
  }
}

describe('homeworldRegionStyle', () => {
  const viewport = { width: 800, height: 600, tx: 0, ty: 0, scale: 1 }

  it('attaches stroke-only paint for homeworld sectors and passes others through', () => {
    const sector = sectorOverlay()
    const visibility = visibilityOverlay()
    const [styledSector, styledVisibility] = applyHomeworldRegionStyle([sector, visibility])

    expect(styledVisibility).toBe(visibility)
    expect(styledVisibility!.paint).toBeUndefined()

    expect(styledSector!.paint).toEqual({
      fillOpacity: 0,
      strokeColor: '#fdba74',
      strokeWidth: 1.5,
      diskStrokes: [
        { strokeColor: '#38bdf8', strokeWidth: 1.75 },
        { strokeColor: '#c084fc', strokeWidth: 1.75 },
      ],
    })
  })

  it('uses error stroke when status is error', () => {
    const paint = homeworldSectorPaint(sectorOverlay({ status: 'error' }))
    expect(paint.strokeColor).toBe('#fca5a5')
  })

  it('falls back to neutral envelope stroke for unknown radii', () => {
    const paint = homeworldSectorPaint(
      sectorOverlay({
        geometry: {
          type: 'boundary',
          vertices: [
            { x: 1, y: 0 },
            { x: 0, y: 1 },
            { x: 0, y: 0.5 },
          ],
          edges: [{ type: 'line' }, { type: 'line' }, { type: 'line' }],
          disks: [{ x: 0, y: 0, radius: 99 }],
        },
      })
    )
    expect(paint.diskStrokes).toEqual([{ strokeColor: '#e2e8f0', strokeWidth: 1.75 }])
  })

  it('uses asserted ownership stroke when possibleOwners include asserted', () => {
    const paint = homeworldSectorPaint(
      sectorOverlay({
        possibleOwners: [
          {
            ownerSlot: 2,
            provenanceKinds: ['asserted'],
            playerLabel: 'alice (The Federation)',
          },
        ],
      })
    )
    expect(paint.strokeColor).toBe('#fbbf24')
    expect(paint.strokeWidth).toBe(2.25)
  })

  it('highlights a selected sector with cyan stroke', () => {
    const [styled] = applyHomeworldRegionStyle([sectorOverlay()], {
      selectedSectorIndex: 0,
    })
    expect(styled!.paint?.strokeColor).toBe('#38bdf8')
  })

  it('layers asserted amber under cyan selection dash when both apply', () => {
    const assertedSector = sectorOverlay({
      possibleOwners: [
        {
          ownerSlot: 2,
          provenanceKinds: ['asserted'],
          playerLabel: 'alice (The Federation)',
        },
      ],
    })
    const paint = homeworldSectorPaint(assertedSector, { isSelected: true })
    expect(paint.strokeColor).toBeUndefined()
    expect(paint.boundaryStrokes).toEqual([
      { strokeColor: '#fbbf24', strokeWidth: 2.25 },
      { strokeColor: '#38bdf8', strokeWidth: 1.5, strokeDasharray: '2 2' },
    ])

    const [styled] = applyHomeworldRegionStyle([assertedSector], { selectedSectorIndex: 0 })
    const group = buildMapRegionOverlayPaneShapes([styled!], viewport).groups[0]!
    expect(group.strokeColor).toBeUndefined()
    expect(group.boundaryStrokes).toEqual([
      { strokeColor: '#fbbf24', strokeWidth: 2.25 },
      { strokeColor: '#38bdf8', strokeWidth: 1.5, strokeDasharray: '2 2' },
    ])
  })

  it('preserves homeworld visual behavior through shared blit', () => {
    const styled = applyHomeworldRegionStyle([sectorOverlay({ status: 'ok' })])
    const group = buildMapRegionOverlayPaneShapes(styled, viewport).groups[0]!
    expect(group.fillOpacity).toBe(0)
    expect(group.strokeColor).toBe('#fdba74')
    expect(group.strokeWidth).toBe(1.5)
    expect(group.disks).toHaveLength(0)
    expect(group.strokeDisks.map((d) => d.strokeColor)).toEqual(['#38bdf8', '#c084fc'])
  })
})
