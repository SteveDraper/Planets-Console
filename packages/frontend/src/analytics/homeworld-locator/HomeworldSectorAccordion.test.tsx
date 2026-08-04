/**
 * RTL tests for homeworld sector accordion: order, titles, expand, selection chrome, tooltips.
 */

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { perspectiveRow } from '../../lib/perspectiveRowTestFixtures'
import { useHomeworldRegionSelectionStore } from '../../stores/homeworldRegionSelection'
import { HomeworldSectorAccordion } from './HomeworldSectorAccordion'
import { HOMEWORLD_SECTOR_KIND } from './homeworldSectorIndex'
import type { HomeworldSectorPanelSection } from './homeworldSectorPanelModel'
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
        mode="readOnly"
        sections={[
          section(1, 'alice (The Federation)', north, [candidate({ planetId: 101 })]),
          section(0, 'Unknown', east, [candidate({ planetId: 100 })], 'ambiguous · 1 candidate homeworld'),
        ]}
        unassigned={[]}
        baselineDegraded={false}
        baselineTurn={null}
        roster={[perspectiveRow(1, 'alice', { raceName: 'The Federation' })]}
        selectedPlanetId={null}
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

  it('expands/collapses and shows preferred-first candidates with planet hover title', async () => {
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
        mode="readOnly"
        sections={[section(1, 'alice (The Federation)', north, rows)]}
        unassigned={[]}
        baselineDegraded={false}
        baselineTurn={null}
        roster={[perspectiveRow(1, 'alice', { raceName: 'The Federation' })]}
        selectedPlanetId={null}
        onSelectPlanet={vi.fn()}
        selectedSectorIndexes={new Set([1])}
        onToggleSectorIndex={vi.fn()}
        compact
      />
    )

    expect(screen.getByText('10')).toBeInTheDocument()
    expect(screen.getByText('20')).toBeInTheDocument()
    const planetRow = screen.getByText('10').closest('tr')
    expect(planetRow).toHaveAttribute(
      'title',
      expect.stringContaining('planet 10 · definite')
    )

    await user.click(screen.getByRole('button', { name: /collapse sector alice/i }))
    expect(screen.queryByText('10')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /expand sector alice/i }))
    expect(screen.getByText('10')).toBeInTheDocument()
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
        mode="readOnly"
        sections={[
          section(
            1,
            'alice (The Federation)',
            north,
            [candidate({ planetId: 101 })],
            'player: alice (The Federation) · 1 candidate homeworld'
          ),
        ]}
        unassigned={[]}
        baselineDegraded={false}
        baselineTurn={null}
        roster={[]}
        selectedPlanetId={null}
        onSelectPlanet={vi.fn()}
        selectedSectorIndexes={new Set([1])}
        onToggleSectorIndex={onToggle}
      />
    )

    const title = screen.getByRole('button', { name: /toggle sector selection: alice/i })
    expect(title).toHaveAttribute(
      'title',
      'player: alice (The Federation) · 1 candidate homeworld'
    )
    await user.click(title)
    expect(onToggle).toHaveBeenCalledWith(1)
  })

  it('keeps assert actions in interactive mode', () => {
    const north = annularSector('homeworld-sector-1', Math.PI / 4, (3 * Math.PI) / 4, {
      playerLabel: 'alice (The Federation)',
    })
    render(
      <HomeworldSectorAccordion
        mode="interactive"
        sections={[
          section(1, 'alice (The Federation)', north, [
            candidate({ planetId: 12, confidenceTier: 'definite' }),
          ]),
        ]}
        unassigned={[]}
        baselineDegraded={true}
        baselineTurn={4}
        roster={[perspectiveRow(1, 'alice', { raceName: 'The Federation' })]}
        selectedPlanetId={null}
        onSelectPlanet={vi.fn()}
        selectedSectorIndexes={new Set([1])}
        onToggleSectorIndex={vi.fn()}
        compact
        mutationPending={false}
        resolveOwnershipTarget={() => ({ keying: 'planet', planetId: 12 })}
        onAssertLocation={vi.fn()}
        onRevokeLocation={vi.fn()}
        onAssertOwnership={vi.fn()}
        onRevokeOwnership={vi.fn()}
      />
    )

    expect(screen.getByRole('status')).toHaveTextContent(/Baseline degraded/)
    const sectionEl = document.querySelector('[data-sector-index="1"]')
    expect(sectionEl).toBeInstanceOf(HTMLElement)
    expect(within(sectionEl as HTMLElement).getByRole('button', { name: /assert hw/i })).toBeInTheDocument()
  })
})
