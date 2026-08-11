import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../stellar-cartography/layers'
import { defaultHomeworldRegionSelectionPreset } from '../../lib/homeworldRegionSelection'
import { perspectiveRow } from '../../lib/perspectiveRowTestFixtures'
import { useSessionStore } from '../../stores/session'
import { useShellStore } from '../../stores/shell'
import {
  HOMEWORLD_REGION_SELECTION_STORAGE_KEY,
  useHomeworldRegionSelectionStore,
} from '../../stores/homeworldRegionSelectionStore'
import { HOMEWORLD_SECTOR_KIND } from './homeworldSectorIndex'
import { HomeworldLocatorTile } from './HomeworldLocatorTile'
import { fetchHomeworldLocatorMap, fetchHomeworldLocatorTable } from './api'

vi.mock('./api', () => ({
  fetchHomeworldLocatorTable: vi.fn(),
  fetchHomeworldLocatorMap: vi.fn(),
  postHomeworldLocatorAssertion: vi.fn(),
  postHomeworldLocatorRefresh: vi.fn(),
}))

function renderTile(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(ui, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  })
}

function seedShellForAnalyticScope() {
  useSessionStore.setState({ name: 'alice', password: '', credentialsRevision: 0 })
  useShellStore.setState({
    selectedGameId: '628580',
    selectedTurn: 5,
    perspectiveOverrideOrdinal: null,
    storageOnlyLoad: false,
    storageAvailablePerspectives: null,
    gameInfoContext: {
      turn: 10,
      isGameFinished: true,
      perspectives: [
        perspectiveRow(1, 'alice', { raceName: 'The Federation' }),
        perspectiveRow(2, 'bob', { raceName: 'The Lizards' }),
      ],
      sectorDisplayName: null,
      stellarCartographyGates: EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
      homeworldInactiveReason: null,
    },
  })
}

describe('HomeworldLocatorTile', () => {
  beforeEach(() => {
    localStorage.removeItem(HOMEWORLD_REGION_SELECTION_STORAGE_KEY)
    useHomeworldRegionSelectionStore.setState({
      regionSelectionPreset: defaultHomeworldRegionSelectionPreset(),
      selectedSectorIndexes: [],
      showEnvelopeOverlays: true,
    })
    useSessionStore.setState({ name: '', password: '', credentialsRevision: 0 })
    useShellStore.setState({
      selectedGameId: null,
      selectedTurn: null,
      perspectiveOverrideOrdinal: null,
      gameInfoContext: null,
      storageOnlyLoad: false,
      storageAvailablePerspectives: null,
    })
    vi.mocked(fetchHomeworldLocatorTable).mockResolvedValue({
      analyticId: 'homeworld-locator',
      available: true,
      baselineDegraded: false,
      rows: [],
    })
    vi.mocked(fetchHomeworldLocatorMap).mockResolvedValue({
      analyticId: 'homeworld-locator',
      available: true,
      baselineDegraded: false,
      regionOverlays: [],
      markers: [],
    })
  })

  it('disables the toggle and shows an inactive hint when unavailable', () => {
    renderTile(
      <HomeworldLocatorTile
        name="Homeworld locator"
        enabled={false}
        supportsMode
        depressed={false}
        onToggle={() => undefined}
        inactiveReason="nohomeworld"
      />
    )
    const checkbox = screen.getByRole('checkbox')
    expect(checkbox).toBeDisabled()
    expect(screen.getByTitle(/no homeworld planets/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /expand homeworld/i })).toBeDisabled()
  })

  it('shows unchecked when persisted enabled but inactive', () => {
    renderTile(
      <HomeworldLocatorTile
        name="Homeworld locator"
        enabled
        supportsMode
        depressed
        onToggle={() => undefined}
        inactiveReason="nohomeworld"
      />
    )
    const checkbox = screen.getByRole('checkbox')
    expect(checkbox).toBeDisabled()
    expect(checkbox).not.toBeChecked()
  })

  it('allows enabling when available and mode is supported', () => {
    renderTile(
      <HomeworldLocatorTile
        name="Homeworld locator"
        enabled={false}
        supportsMode
        depressed={false}
        onToggle={() => undefined}
        inactiveReason={null}
      />
    )
    expect(screen.getByRole('checkbox')).not.toBeDisabled()
  })

  it('expands to expose show overlays and panel; hides region selection without sectors', async () => {
    const user = userEvent.setup()
    renderTile(
      <HomeworldLocatorTile
        name="Homeworld locator"
        enabled
        supportsMode
        depressed
        onToggle={() => undefined}
        inactiveReason={null}
      />
    )

    await user.click(screen.getByRole('button', { name: /expand homeworld/i }))
    expect(screen.getByRole('checkbox', { name: /show overlays/i })).toBeChecked()
    expect(
      screen.queryByRole('radiogroup', { name: /homeworld region selection/i })
    ).not.toBeInTheDocument()
    expect(screen.getByText(/load game info and choose a turn/i)).toBeInTheDocument()

    await user.click(screen.getByRole('checkbox', { name: /show overlays/i }))
    expect(useHomeworldRegionSelectionStore.getState().showEnvelopeOverlays).toBe(false)
    expect(localStorage.getItem(HOMEWORLD_REGION_SELECTION_STORAGE_KEY)).toContain(
      '"showEnvelopeOverlays":false'
    )
  })

  it('shows region selection when sector overlays are present', async () => {
    const user = userEvent.setup()
    seedShellForAnalyticScope()
    vi.mocked(fetchHomeworldLocatorMap).mockResolvedValue({
      analyticId: 'homeworld-locator',
      available: true,
      baselineDegraded: false,
      regionOverlays: [
        {
          kind: HOMEWORLD_SECTOR_KIND,
          id: 'homeworld-sector-0',
          fillColor: '#f97316',
          fillOpacity: 0,
          geometry: {
            type: 'boundary',
            vertices: [
              { x: 0, y: 0 },
              { x: 1, y: 0 },
              { x: 1, y: 1 },
              { x: 0, y: 1 },
            ],
            edges: [
              { type: 'line' },
              { type: 'line' },
              { type: 'line' },
              { type: 'line' },
            ],
          },
        },
      ],
      markers: [],
    })
    renderTile(
      <HomeworldLocatorTile
        name="Homeworld locator"
        enabled
        supportsMode
        depressed
        onToggle={() => undefined}
        inactiveReason={null}
      />
    )

    await user.click(screen.getByRole('button', { name: /expand homeworld/i }))
    expect(
      await screen.findByRole('radiogroup', { name: /homeworld region selection/i })
    ).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /show overlays/i })).toBeChecked()

    await user.click(screen.getByRole('radio', { name: 'Pinned' }))
    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe('pinned')
    expect(localStorage.getItem(HOMEWORLD_REGION_SELECTION_STORAGE_KEY)).toContain('pinned')
  })
})
