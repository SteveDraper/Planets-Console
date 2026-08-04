import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { defaultHomeworldRegionSelectionPreset } from './homeworldRegionSelection'
import { HomeworldLocatorTile } from './HomeworldLocatorTile'
import {
  HOMEWORLD_REGION_SELECTION_STORAGE_KEY,
  useHomeworldRegionSelectionStore,
} from '../../stores/homeworldRegionSelection'
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

describe('HomeworldLocatorTile', () => {
  beforeEach(() => {
    localStorage.removeItem(HOMEWORLD_REGION_SELECTION_STORAGE_KEY)
    useHomeworldRegionSelectionStore.setState({
      regionSelectionPreset: defaultHomeworldRegionSelectionPreset(),
      selectedSectorIndexes: null,
      showEnvelopeOverlays: true,
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

  it('expands to expose region selection, show overlays, panel, and persists changes', async () => {
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
    expect(
      screen.getByRole('radiogroup', { name: /homeworld region selection/i })
    ).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /show overlays/i })).toBeChecked()
    expect(screen.getByText(/load game info and choose a turn/i)).toBeInTheDocument()

    await user.click(screen.getByRole('radio', { name: 'Pinned' }))
    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe('pinned')
    expect(localStorage.getItem(HOMEWORLD_REGION_SELECTION_STORAGE_KEY)).toContain('pinned')

    await user.click(screen.getByRole('checkbox', { name: /show overlays/i }))
    expect(useHomeworldRegionSelectionStore.getState().showEnvelopeOverlays).toBe(false)
    expect(localStorage.getItem(HOMEWORLD_REGION_SELECTION_STORAGE_KEY)).toContain(
      '"showEnvelopeOverlays":false'
    )
  })
})
