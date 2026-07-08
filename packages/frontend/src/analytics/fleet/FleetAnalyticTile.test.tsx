import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ComponentProps } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FleetAnalyticTile } from './FleetAnalyticTile'
import { seedShellViewpoint } from './fleetTestShell'
import { useFleetPlayerVisibilityStore } from '../../stores/fleetPlayerVisibility'
import { useShellStore } from '../../stores/shell'

vi.mock('../../api/bff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/bff')>()
  return {
    ...actual,
    fetchAnalyticTable: vi.fn(),
  }
})

import { fetchAnalyticTable } from '../../api/bff'

function createWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

function renderTile(overrides: Partial<ComponentProps<typeof FleetAnalyticTile>> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <FleetAnalyticTile
      name="Fleet"
      enabled
      supportsMode
      depressed
      onToggle={() => {}}
      {...overrides}
    />,
    { wrapper: createWrapper(client) }
  )
}

describe('FleetAnalyticTile', () => {
  beforeEach(() => {
    useFleetPlayerVisibilityStore.setState({ overrides: {} })
    useShellStore.setState({
      selectedGameId: null,
      gameInfoContext: null,
      selectedTurn: null,
      perspectiveOverrideOrdinal: null,
      storageOnlyLoad: false,
      storageAvailablePerspectives: null,
    })
    seedShellViewpoint(1)
    vi.mocked(fetchAnalyticTable).mockResolvedValue({
      analyticId: 'scores',
      columns: ['Race (player)'],
      rows: [],
      rowPlayerIds: [],
    })
  })

  it('hides player checkboxes until expanded', () => {
    renderTile()
    expect(screen.queryByLabelText('Alice')).not.toBeInTheDocument()
  })

  it('shows all players enabled by default', async () => {
    const user = userEvent.setup()
    renderTile()
    await user.click(screen.getByLabelText('Expand Fleet player visibility'))
    expect(screen.getByLabelText('Alice')).toBeChecked()
    expect(screen.getByLabelText('Bob')).toBeChecked()
  })

  it('persists player toggle changes and updates checkbox state', async () => {
    const user = userEvent.setup()
    renderTile()
    await user.click(screen.getByLabelText('Expand Fleet player visibility'))
    const bob = screen.getByLabelText('Bob')
    expect(bob).toBeChecked()
    await user.click(bob)
    expect(bob).not.toBeChecked()
    expect(useFleetPlayerVisibilityStore.getState().isFleetPlayerVisible(9, 8)).toBe(false)
  })
})
