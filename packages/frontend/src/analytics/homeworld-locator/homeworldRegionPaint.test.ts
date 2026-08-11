import { describe, expect, it } from 'vitest'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { buildMapRegionOverlayPaneShapes } from '../../lib/mapRegionOverlay'
import {
  HOMEWORLD_PLANET_ENVELOPE_KIND,
  HOMEWORLD_SECTOR_KIND,
} from './homeworldSectorIndex'
import { buildHomeworldRegionOverlaysForPaint, applyHomeworldRegionSelection } from './homeworldRegionPaint'

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

function planetEnvelope(
  planetId: number,
  disks: { x: number; y: number; radius: number }[]
): MapRegionOverlay {
  return {
    kind: HOMEWORLD_PLANET_ENVELOPE_KIND,
    id: `homeworld-planet-envelope-${planetId}`,
    fillColor: '#f97316',
    fillOpacity: 0,
    isPinned: true,
    geometry: {
      type: 'boundary',
      vertices: [],
      edges: [],
      disks,
    },
  }
}

describe('buildHomeworldRegionOverlaysForPaint', () => {
  const viewport = { width: 800, height: 600, tx: 0, ty: 0, scale: 1 }
  const disks = [
    { x: 150, y: 50, radius: 81 },
    { x: 150, y: 50, radius: 162 },
  ]

  it('filters outlines by selected indexes via applyHomeworldRegionSelection', () => {
    const overlays = [
      sector('homeworld-sector-0', { isPinned: true, disks }),
      sector('homeworld-sector-2', { disks: [{ x: 1, y: 1, radius: 81 }] }),
      visibilityOverlay(),
    ]
    expect(applyHomeworldRegionSelection(overlays, [0, 2], true).map((o) => o.id)).toEqual([
      'homeworld-sector-0',
      'homeworld-sector-2',
      'vis-1',
    ])
    expect(applyHomeworldRegionSelection(overlays, [], true).map((o) => o.id)).toEqual([
      'vis-1',
    ])
  })

  it('paints outlines only for selected sector indexes', () => {
    const overlays = [
      sector('homeworld-sector-0', { isPinned: true, disks }),
      sector('homeworld-sector-2', { disks: [{ x: 1, y: 1, radius: 81 }] }),
      visibilityOverlay(),
    ]
    const painted = buildHomeworldRegionOverlaysForPaint({
      overlays,
      effectiveSelectedSectorIndexes: [0],
      showEnvelopeOverlays: true,
      assertFocusSelection: null,
      homeworldMarkers: [],
    })
    expect(painted.map((o) => o.id)).toEqual(['homeworld-sector-0', 'vis-1'])
  })

  it('paints every effective index without re-deriving from preset', () => {
    const painted = buildHomeworldRegionOverlaysForPaint({
      overlays: [
        sector('homeworld-sector-0', { disks }),
        sector('homeworld-sector-2', { disks }),
        visibilityOverlay(),
      ],
      effectiveSelectedSectorIndexes: [0, 2],
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

  it('omits all homeworld outlines when the selected set is empty', () => {
    const painted = buildHomeworldRegionOverlaysForPaint({
      overlays: [sector('homeworld-sector-0', { disks }), visibilityOverlay()],
      effectiveSelectedSectorIndexes: [],
      showEnvelopeOverlays: true,
      assertFocusSelection: null,
      homeworldMarkers: [],
    })
    expect(painted.map((o) => o.id)).toEqual(['vis-1'])
  })

  it('strips envelope disks when Show overlays is off; keeps outlines for selected', () => {
    const painted = buildHomeworldRegionOverlaysForPaint({
      overlays: [sector('homeworld-sector-0', { disks }), visibilityOverlay()],
      effectiveSelectedSectorIndexes: [0],
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
      effectiveSelectedSectorIndexes: [0],
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
      effectiveSelectedSectorIndexes: [1],
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
      effectiveSelectedSectorIndexes: [0, 1],
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
      effectiveSelectedSectorIndexes: [0],
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
      effectiveSelectedSectorIndexes: [0],
      showEnvelopeOverlays: true,
      assertFocusSelection: { kind: 'planet', planetId: 42 },
      homeworldMarkers: [{ planetId: 42, x: 5, y: 5 }],
    })
    expect(painted[0]!.paint?.strokeColor).toBe('#38bdf8')
  })

  it('paints planet envelopes when Show overlays is on and strips them when off', () => {
    const envelopes = [planetEnvelope(7, disks), visibilityOverlay()]
    expect(applyHomeworldRegionSelection(envelopes, [], true).map((o) => o.id)).toEqual([
      'homeworld-planet-envelope-7',
      'vis-1',
    ])
    expect(applyHomeworldRegionSelection(envelopes, [], false).map((o) => o.id)).toEqual([
      'vis-1',
    ])

    const paintedOn = buildHomeworldRegionOverlaysForPaint({
      overlays: envelopes,
      effectiveSelectedSectorIndexes: [],
      showEnvelopeOverlays: true,
      assertFocusSelection: null,
      homeworldMarkers: [],
    })
    expect(paintedOn.map((o) => o.id)).toEqual(['homeworld-planet-envelope-7', 'vis-1'])
    const group = buildMapRegionOverlayPaneShapes(
      paintedOn.filter((o) => o.kind === HOMEWORLD_PLANET_ENVELOPE_KIND),
      viewport
    ).groups[0]!
    expect(group.strokeDisks.map((d) => d.strokeColor)).toEqual(['#38bdf8', '#c084fc'])
    expect(group.boundaryPath).toBeUndefined()

    const paintedOff = buildHomeworldRegionOverlaysForPaint({
      overlays: envelopes,
      effectiveSelectedSectorIndexes: [],
      showEnvelopeOverlays: false,
      assertFocusSelection: null,
      homeworldMarkers: [],
    })
    expect(paintedOff.map((o) => o.id)).toEqual(['vis-1'])
  })
})
