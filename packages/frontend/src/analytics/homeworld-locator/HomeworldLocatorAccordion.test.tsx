/**
 * RTL tests for homeworld sector accordion: order, titles, expand, selection chrome, tooltips.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { perspectiveRow } from '../../lib/perspectiveRowTestFixtures'
import { useHomeworldRegionSelectionStore } from '../../stores/homeworldRegionSelectionStore'
import { HomeworldPlayerAccordion, HomeworldSectorAccordion } from './HomeworldLocatorAccordion'
import { HOMEWORLD_SECTOR_KIND } from './homeworldSectorIndex'
import type {
  HomeworldPlayerPanelSection,
  HomeworldSectorPanelSection,
} from './homeworldLocatorPanelModel'
import type { HomeworldCandidateRecord } from './wireSchema'

function annularSector(
  id: string,
  angleStart: number,
  angleEnd: number,
  overrides: Partial<MapRegionOverlay> = {}
): MapRegionOverlay {
  const rOuter = 200
  const rInner = 100
  return {
    kind: HOMEWORLD_SECTOR_KIND,
    id,
    fillColor: '#f97316',
    fillOpacity: 0,
    geometry: {
      type: 'boundary',
      vertices: [
        { x: rOuter * Math.cos(angleStart), y: rOuter * Math.sin(angleStart) },
        { x: rOuter * Math.cos(angleEnd), y: rOuter * Math.sin(angleEnd) },
        { x: rInner * Math.cos(angleEnd), y: rInner * Math.sin(angleEnd) },
        { x: rInner * Math.cos(angleStart), y: rInner * Math.sin(angleStart) },
      ],
      edges: [
        { type: 'arc', centerX: 0, centerY: 0, clockwise: false },
        { type: 'line' },
        { type: 'arc', centerX: 0, centerY: 0, clockwise: true },
        { type: 'line' },
      ],
    },
    isPinned: false,
    status: 'ok',
    candidateCount: 0,
    ...overrides,
  }
}

function candidate(
  overrides: Partial<HomeworldCandidateRecord> & Pick<HomeworldCandidateRecord, 'planetId'>
): HomeworldCandidateRecord {
  return {
    planetId: overrides.planetId,
    perspective: 'perspective' in overrides ? overrides.perspective! : 1,
    confidenceTier: overrides.confidenceTier ?? 'possible',
    attribution: overrides.attribution ?? 'inferred',
    assertedCue: overrides.assertedCue ?? false,
    locationAsserted: overrides.locationAsserted ?? false,
    isMostProbable: overrides.isMostProbable ?? false,
  }
}

function section(
  sectorIndex: number,
  title: string,
  overlay: MapRegionOverlay,
  candidates: HomeworldCandidateRecord[],
  titleHover: string | null = null
): HomeworldSectorPanelSection {
  return { sectorIndex, title, overlay, candidates, titleHover }
}

describe('HomeworldSectorAccordion', () => {
  beforeEach(() => {
    useHomeworldRegionSelectionStore.setState({
      regionSelectionPreset: 'selected',
      selectedSectorIndexes: [1],
      showEnvelopeOverlays: true,
    })
  })

  it('renders sector titles in given order with selection chrome', () => {
    const north = annularSector('homeworld-sector-1', Math.PI / 4, (3 * Math.PI) / 4, {
      playerLabel: 'alice (The Federation)',
      candidateCount: 1,
    })
    const east = annularSector('homeworld-sector-0', -Math.PI / 4, Math.PI / 4, {
      candidateCount: 1,
    })
    render(
      <HomeworldSectorAccordion
        sections={[
          section(1, 'alice (The Federation)', north, [candidate({ planetId: 101 })]),
          section(0, 'Unknown', east, [candidate({ planetId: 100 })], 'ambiguous · 1 candidate homeworld'),
        ]}
        unassigned={[]}
        baselineDegraded={false}
        baselineTurn={null}
        roster={[perspectiveRow(1, 'alice', { raceName: 'The Federation' })]}
        onSelectPlanet={vi.fn()}
        selectedSectorIndexes={new Set([1])}
        onToggleSectorIndex={vi.fn()}
      />
    )

    const titles = screen.getAllByRole('button', { name: /toggle sector selection/i })
    expect(titles.map((el) => el.textContent)).toEqual([
      'alice (The Federation)',
      'Unknown',
    ])
    expect(screen.getByRole('button', { name: /toggle sector selection: alice/i })).toHaveAttribute(
      'aria-pressed',
      'true'
    )
    expect(screen.getByRole('button', { name: /toggle sector selection: Unknown/i })).toHaveAttribute(
      'aria-pressed',
      'false'
    )
    const northSection = document.querySelector('[data-sector-index="1"]')
    const eastSection = document.querySelector('[data-sector-index="0"]')
    expect(northSection).toHaveAttribute('data-selected', 'true')
    expect(eastSection).toHaveAttribute('data-selected', 'false')
  })

  it('starts collapsed and expands to show preferred-first candidates', async () => {
    const user = userEvent.setup()
    const north = annularSector('homeworld-sector-1', Math.PI / 4, (3 * Math.PI) / 4, {
      playerLabel: 'alice (The Federation)',
    })
    const rows = [
      candidate({ planetId: 10, confidenceTier: 'definite' }),
      candidate({ planetId: 20, confidenceTier: 'possible', isMostProbable: true }),
    ]
    render(
      <HomeworldSectorAccordion
        sections={[section(1, 'alice (The Federation)', north, rows)]}
        unassigned={[]}
        baselineDegraded={false}
        baselineTurn={null}
        roster={[perspectiveRow(1, 'alice', { raceName: 'The Federation' })]}
        onSelectPlanet={vi.fn()}
        selectedSectorIndexes={new Set([1])}
        onToggleSectorIndex={vi.fn()}
        compact
      />
    )

    expect(screen.queryByText('10')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /expand sector alice/i }))
    expect(screen.getByText('10')).toBeInTheDocument()
    expect(screen.getByText('20')).toBeInTheDocument()
    const planetRow = screen.getByText('10').closest('tr')
    expect(planetRow).toHaveAttribute(
      'title',
      expect.stringContaining('planet 10 · definite')
    )

    await user.click(screen.getByRole('button', { name: /collapse sector alice/i }))
    expect(screen.queryByText('10')).not.toBeInTheDocument()
  })

  it('toggles sector selection from the title bar', async () => {
    const user = userEvent.setup()
    const onToggle = vi.fn()
    const north = annularSector('homeworld-sector-1', Math.PI / 4, (3 * Math.PI) / 4, {
      playerLabel: 'alice (The Federation)',
      candidateCount: 1,
    })
    render(
      <HomeworldSectorAccordion
        sections={[
          section(
            1,
            'alice (The Federation)',
            north,
            [candidate({ planetId: 101 })],
            'player: alice (The Federation) · definite · 1 candidate homeworld'
          ),
        ]}
        unassigned={[]}
        baselineDegraded={false}
        baselineTurn={null}
        roster={[]}
        onSelectPlanet={vi.fn()}
        selectedSectorIndexes={new Set([1])}
        onToggleSectorIndex={onToggle}
      />
    )

    const title = screen.getByRole('button', { name: /toggle sector selection: alice/i })
    expect(title).toHaveAttribute(
      'title',
      'player: alice (The Federation) · definite · 1 candidate homeworld'
    )
    await user.click(title)
    expect(onToggle).toHaveBeenCalledWith(1)
  })

  it('shows degraded baseline and omits assert controls (map menu owns asserts)', async () => {
    const user = userEvent.setup()
    const north = annularSector('homeworld-sector-1', Math.PI / 4, (3 * Math.PI) / 4, {
      playerLabel: 'alice (The Federation)',
    })
    render(
      <HomeworldSectorAccordion
        sections={[
          section(1, 'alice (The Federation)', north, [
            candidate({ planetId: 12, confidenceTier: 'definite' }),
          ]),
        ]}
        unassigned={[]}
        baselineDegraded={true}
        baselineTurn={4}
        roster={[perspectiveRow(1, 'alice', { raceName: 'The Federation' })]}
        onSelectPlanet={vi.fn()}
        selectedSectorIndexes={new Set([1])}
        onToggleSectorIndex={vi.fn()}
        compact
      />
    )

    expect(screen.getByRole('status')).toHaveTextContent(/Baseline degraded/)
    expect(screen.queryByText('12')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /expand sector alice/i }))
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /assert hw/i })).not.toBeInTheDocument()
  })

  it('omits Owner under sector sections but keeps it for Unassigned', async () => {
    const user = userEvent.setup()
    const north = annularSector('homeworld-sector-1', Math.PI / 4, (3 * Math.PI) / 4, {
      playerLabel: 'alice (The Federation)',
    })
    render(
      <HomeworldSectorAccordion
        sections={[
          section(1, 'alice (The Federation)', north, [
            candidate({ planetId: 12, perspective: 1, confidenceTier: 'definite' }),
          ]),
        ]}
        unassigned={[candidate({ planetId: 99, perspective: 2 })]}
        baselineDegraded={false}
        baselineTurn={null}
        roster={[
          perspectiveRow(1, 'alice', { raceName: 'The Federation' }),
          perspectiveRow(2, 'bob', { raceName: 'The Lizards' }),
        ]}
        onSelectPlanet={vi.fn()}
        selectedSectorIndexes={new Set([1])}
        onToggleSectorIndex={vi.fn()}
        compact
      />
    )

    expect(screen.getByText('bob (The Lizards)')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /expand sector alice/i }))
    const sectorEl = document.querySelector('[data-sector-index="1"]')
    expect(sectorEl).toBeInstanceOf(HTMLElement)
    expect(sectorEl!.textContent).toContain('12')
    // Sector title carries ownership; candidate row must not repeat owner label.
    expect(sectorEl!.querySelector('tbody')?.textContent).not.toContain('alice (The Federation)')
  })
})


describe('HomeworldPlayerAccordion', () => {
  it('renders player sections in given order and expands sparse candidates', async () => {
    const user = userEvent.setup()
    const sections: HomeworldPlayerPanelSection[] = [
      {
        playerOrdinal: 1,
        playerId: 2,
        title: 'alice (The Federation)',
        candidates: [candidate({ planetId: 12, perspective: 1, confidenceTier: 'definite' })],
      },
      {
        playerOrdinal: 2,
        playerId: 847,
        title: 'bob (The Lizards)',
        candidates: [],
      },
    ]
    render(
      <HomeworldPlayerAccordion
        sections={sections}
        baselineDegraded={false}
        baselineTurn={null}
        roster={[
          perspectiveRow(1, 'alice', { playerId: 2, raceName: 'The Federation' }),
          perspectiveRow(2, 'bob', { playerId: 847, raceName: 'The Lizards' }),
        ]}
        onSelectPlanet={vi.fn()}
        compact
      />
    )

    expect(screen.getByText('alice (The Federation)')).toBeInTheDocument()
    expect(screen.getByText('bob (The Lizards)')).toBeInTheDocument()
    expect(screen.queryByText('Unassigned')).not.toBeInTheDocument()
    expect(screen.queryByText('12')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /expand player alice/i }))
    expect(screen.getByText('12')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /expand player bob/i }))
    expect(screen.getByText('No pinned homeworld.')).toBeInTheDocument()
  })
})
