import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ComponentProps } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FleetAnalyticTile } from './FleetAnalyticTile'
import { seedShellViewpoint } from './fleetTestShell'
import { useFleetPlayerVisibilityStore } from '../../stores/fleetPlayerVisibility'
import { useFleetHeadingTrailExtendStore } from '../../stores/fleetHeadingTrailExtend'
import {
  installPlayerColorsStorePort,
  resetPlayerColorsStoreState,
  usePlayerColorsStore,
} from '../../stores/playerColors'
import { defaultColorForPlayerId, resetPlayerColorResolutionPort } from '../../lib/playerColor'
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
    useFleetHeadingTrailExtendStore.setState({ extendTurns: 0 })
    resetPlayerColorResolutionPort()
    resetPlayerColorsStoreState()
    installPlayerColorsStorePort()
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

  it('updates heading trail extend turns from the sidebar select', async () => {
    const user = userEvent.setup()
    renderTile()
    await user.click(screen.getByLabelText('Expand Fleet player visibility'))
    const trailSelect = screen.getByLabelText('Fleet heading trail extend turns')
    expect(trailSelect).toHaveValue('0')
    await user.selectOptions(trailSelect, '3')
    expect(useFleetHeadingTrailExtendStore.getState().extendTurns).toBe(3)
    expect(trailSelect).toHaveValue('3')
  })

  it('disables the trail extend control on future shell turns', async () => {
    const user = userEvent.setup()
    useShellStore.setState((state) => ({
      ...state,
      selectedTurn: 12,
      gameInfoContext: state.gameInfoContext
        ? { ...state.gameInfoContext, turn: 10 }
        : null,
    }))
    renderTile()
    await user.click(screen.getByLabelText('Expand Fleet player visibility'))
    const trailSelect = screen.getByLabelText('Fleet heading trail extend turns')
    expect(trailSelect).toBeDisabled()
  })

  it('shows a player color swatch matching the paint color and a full-label title', async () => {
    const user = userEvent.setup()
    usePlayerColorsStore.getState().setPlayerColorOverride(8, '#112233')
    renderTile()
    await user.click(screen.getByLabelText('Expand Fleet player visibility'))

    const aliceRow = screen.getByLabelText('Alice').closest('label')
    expect(aliceRow).toHaveAttribute('title', 'Alice')
    const aliceSwatch = screen.getByTestId('fleet-player-color-8')
    expect(aliceSwatch).toHaveStyle({ backgroundColor: '#112233' })
    expect(aliceSwatch).not.toHaveClass('opacity-50')

    const bobSwatch = screen.getByTestId('fleet-player-color-9')
    expect(bobSwatch).toHaveStyle({ backgroundColor: defaultColorForPlayerId(9) })
  })

  it('keeps the color swatch visible (dimmed) when a player is unchecked', async () => {
    const user = userEvent.setup()
    renderTile()
    await user.click(screen.getByLabelText('Expand Fleet player visibility'))
    await user.click(screen.getByLabelText('Bob'))
    const bobSwatch = screen.getByTestId('fleet-player-color-9')
    expect(bobSwatch).toBeInTheDocument()
    expect(bobSwatch).toHaveClass('opacity-50')
    expect(bobSwatch).toHaveStyle({ backgroundColor: defaultColorForPlayerId(9) })
  })
})
