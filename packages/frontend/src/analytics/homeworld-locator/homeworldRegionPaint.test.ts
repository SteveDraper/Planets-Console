import { describe, expect, it } from 'vitest'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { buildMapRegionOverlayPaneShapes } from '../../lib/mapRegionOverlay'
import { HOMEWORLD_SECTOR_KIND } from './homeworldSectorIndex'
import { buildHomeworldRegionOverlaysForPaint } from './homeworldRegionPaint'

function sector(
  id: string,
  options: {
    isPinned?: boolean
    disks?: { x: number; y: number; radius: number }[]
    possibleOwners?: MapRegionOverlay['possibleOwners']
  } = {}
): MapRegionOverlay {
  return {
    kind: HOMEWORLD_SECTOR_KIND,
    id,
    fillColor: '#f97316',
    fillOpacity: 0.2,
    isPinned: options.isPinned ?? false,
    possibleOwners: options.possibleOwners,
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
      ...(options.disks != null ? { disks: options.disks } : {}),
    },
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

describe('buildHomeworldRegionOverlaysForPaint', () => {
  const viewport = { width: 800, height: 600, tx: 0, ty: 0, scale: 1 }
  const disks = [
    { x: 150, y: 50, radius: 81 },
    { x: 150, y: 50, radius: 162 },
  ]

  it('paints outlines only for selected sector indexes', () => {
    const overlays = [
      sector('homeworld-sector-0', { isPinned: true, disks }),
      sector('homeworld-sector-2', { disks: [{ x: 1, y: 1, radius: 81 }] }),
      visibilityOverlay(),
    ]
    const painted = buildHomeworldRegionOverlaysForPaint({
      overlays,
      regionSelectionPreset: 'selected',
      selectedSectorIndexes: [0],
      showEnvelopeOverlays: true,
      assertFocusSelection: null,
      homeworldMarkers: [],
    })
    expect(painted.map((o) => o.id)).toEqual(['homeworld-sector-0', 'vis-1'])
  })

  it('treats selected + null stored as all homeworld sectors', () => {
    const painted = buildHomeworldRegionOverlaysForPaint({
      overlays: [
        sector('homeworld-sector-0', { disks }),
        sector('homeworld-sector-2', { disks }),
        visibilityOverlay(),
      ],
      regionSelectionPreset: 'selected',
      selectedSectorIndexes: null,
      showEnvelopeOverlays: true,
      assertFocusSelection: null,
      homeworldMarkers: [],
    })
    expect(painted.map((o) => o.id)).toEqual([
      'homeworld-sector-0',
      'homeworld-sector-2',
      'vis-1',
    ])
  })

  it('derives pinned outlines from overlay facts without stored indexes', () => {
    const painted = buildHomeworldRegionOverlaysForPaint({
      overlays: [
        sector('homeworld-sector-0', { isPinned: true, disks }),
        sector('homeworld-sector-2', { disks }),
        visibilityOverlay(),
      ],
      regionSelectionPreset: 'pinned',
      selectedSectorIndexes: null,
      showEnvelopeOverlays: true,
      assertFocusSelection: null,
      homeworldMarkers: [],
    })
    expect(painted.map((o) => o.id)).toEqual(['homeworld-sector-0', 'vis-1'])
  })

  it('omits all homeworld outlines when the selected set is empty', () => {
    const painted = buildHomeworldRegionOverlaysForPaint({
      overlays: [sector('homeworld-sector-0', { disks }), visibilityOverlay()],
      regionSelectionPreset: 'selected',
      selectedSectorIndexes: [],
      showEnvelopeOverlays: true,
      assertFocusSelection: null,
      homeworldMarkers: [],
    })
    expect(painted.map((o) => o.id)).toEqual(['vis-1'])
  })

  it('strips envelope disks when Show overlays is off; keeps outlines for selected', () => {
    const painted = buildHomeworldRegionOverlaysForPaint({
      overlays: [sector('homeworld-sector-0', { disks }), visibilityOverlay()],
      regionSelectionPreset: 'selected',
      selectedSectorIndexes: [0],
      showEnvelopeOverlays: false,
      assertFocusSelection: null,
      homeworldMarkers: [],
    })
    const hw = painted.find((o) => o.id === 'homeworld-sector-0')
    expect(hw).toBeDefined()
    expect(hw!.geometry.type).toBe('boundary')
    if (hw!.geometry.type === 'boundary') {
      expect(hw!.geometry.disks).toBeUndefined()
    }
    const group = buildMapRegionOverlayPaneShapes([hw!], viewport).groups[0]!
    expect(group.strokeDisks).toHaveLength(0)
    expect(group.strokeColor).toBe('#fdba74')
  })

  it('keeps 81/162 envelope rings when Show overlays is on for selected sectors', () => {
    const painted = buildHomeworldRegionOverlaysForPaint({
      overlays: [sector('homeworld-sector-0', { disks })],
      regionSelectionPreset: 'selected',
      selectedSectorIndexes: [0],
      showEnvelopeOverlays: true,
      assertFocusSelection: null,
      homeworldMarkers: [],
    })
    const group = buildMapRegionOverlayPaneShapes(painted, viewport).groups[0]!
    expect(group.strokeDisks.map((d) => d.strokeColor)).toEqual(['#38bdf8', '#c084fc'])
  })

  it('does not paint envelopes for sectors outside the selected set', () => {
    const painted = buildHomeworldRegionOverlaysForPaint({
      overlays: [
        sector('homeworld-sector-0', { disks }),
        sector('homeworld-sector-1', { disks }),
      ],
      regionSelectionPreset: 'selected',
      selectedSectorIndexes: [1],
      showEnvelopeOverlays: true,
      assertFocusSelection: null,
      homeworldMarkers: [],
    })
    expect(painted.map((o) => o.id)).toEqual(['homeworld-sector-1'])
  })

  it('applies assert-focus cyan stroke independently of multi-select membership', () => {
    const painted = buildHomeworldRegionOverlaysForPaint({
      overlays: [
        sector('homeworld-sector-0', { disks }),
        sector('homeworld-sector-1', { disks }),
      ],
      regionSelectionPreset: 'selected',
      selectedSectorIndexes: [0, 1],
      showEnvelopeOverlays: false,
      assertFocusSelection: { kind: 'sector', sectorIndex: 1 },
      homeworldMarkers: [],
    })
    const focused = painted.find((o) => o.id === 'homeworld-sector-1')
    const other = painted.find((o) => o.id === 'homeworld-sector-0')
    expect(focused!.paint?.strokeColor).toBe('#38bdf8')
    expect(other!.paint?.strokeColor).toBe('#fdba74')
  })

  it('does not invent assert-focus outline when the focused sector is not multi-selected', () => {
    const painted = buildHomeworldRegionOverlaysForPaint({
      overlays: [
        sector('homeworld-sector-0', { disks }),
        sector('homeworld-sector-1', { disks }),
      ],
      regionSelectionPreset: 'selected',
      selectedSectorIndexes: [0],
      showEnvelopeOverlays: true,
      assertFocusSelection: { kind: 'sector', sectorIndex: 1 },
      homeworldMarkers: [],
    })
    expect(painted.map((o) => o.id)).toEqual(['homeworld-sector-0'])
    expect(painted[0]!.paint?.strokeColor).toBe('#fdba74')
  })

  it('resolves assert-focus from a selected planet marker hit-test', () => {
    const boxSector: MapRegionOverlay = {
      kind: HOMEWORLD_SECTOR_KIND,
      id: 'homeworld-sector-0',
      fillColor: '#f97316',
      fillOpacity: 0,
      geometry: {
        type: 'boundary',
        vertices: [
          { x: 0, y: 0 },
          { x: 10, y: 0 },
          { x: 10, y: 10 },
          { x: 0, y: 10 },
        ],
        edges: [{ type: 'line' }, { type: 'line' }, { type: 'line' }, { type: 'line' }],
      },
    }
    const painted = buildHomeworldRegionOverlaysForPaint({
      overlays: [boxSector],
      regionSelectionPreset: 'selected',
      selectedSectorIndexes: [0],
      showEnvelopeOverlays: true,
      assertFocusSelection: { kind: 'planet', planetId: 42 },
      homeworldMarkers: [{ planetId: 42, x: 5, y: 5 }],
    })
    expect(painted[0]!.paint?.strokeColor).toBe('#38bdf8')
  })
})
