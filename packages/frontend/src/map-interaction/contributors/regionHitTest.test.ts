import { describe, it, expect, vi } from 'vitest'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import {
  hitTestRegionLinesAtPointer,
  regionOverlayHoverLinesAtClient,
} from './regionHitTest'
import type { MapHitContext } from '../mapInteractionContributorTypes'

const pane = document.createElement('div')

function hitAt(x: number, y: number): MapHitContext {
  return {
    clientPos: { x, y },
    hitEpoch: 1,
    domNode: pane,
    transform: [0, 0, 1],
  }
}


vi.mock('../../lib/mapFlowGeometry', () => ({
  clientToFlowPosition: (clientX: number, clientY: number) => ({
    x: clientX,
    y: clientY,
  }),
}))

vi.mock('../../lib/planetSpatialGrid', () => ({
  flowCenterToPlanet: (x: number, y: number) => ({ px: x, py: y }),
}))

vi.mock('../../lib/mapRegionOverlayHitTest', () => ({
  collectRegionOverlayHoverSummaries: () => ['region line'],
}))

const sampleOverlay: MapRegionOverlay = {
  kind: 'homeworld-sector',
  id: 's1',
  fillColor: '#fff',
  fillOpacity: 0.2,
  isPinned: true,
  candidateCount: 1,
  playerLabel: 'alice',
  geometry: { type: 'coverage', disks: [], patches: [] },
}

describe('regionOverlayHoverLinesAtClient', () => {
  it('derives lines from client pointer without attaching listeners', () => {
    vi.spyOn(pane, 'addEventListener')
    expect(
      regionOverlayHoverLinesAtClient(
        [sampleOverlay],
        50,
        60,
        pane,
        [0, 0, 1]
      )
    ).toEqual(['region line'])
    expect(pane.addEventListener).not.toHaveBeenCalled()
  })
})

describe('hitTestRegionLinesAtPointer', () => {
  it('returns empty when there are no overlays', () => {
    expect(hitTestRegionLinesAtPointer(hitAt(50, 60), [])).toEqual([])
  })

  it('hit-tests overlays under the pointer', () => {
    expect(
      hitTestRegionLinesAtPointer(hitAt(50, 60), [sampleOverlay])
    ).toEqual(['region line'])
  })
})
