import { beforeEach, describe, expect, it } from 'vitest'
import type { ComponentProps } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FleetAnalyticTile } from './FleetAnalyticTile'
import { useFleetPlayerVisibilityStore } from '../../stores/fleetPlayerVisibility'
import { useShellStore } from '../../stores/shell'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../stellar-cartography/layers'

const players = [
  { ordinal: 1, playerId: 8, name: 'Alice', raceName: null },
  { ordinal: 2, playerId: 9, name: 'Bob', raceName: null },
] as const

function seedShellViewpoint(viewpointName: 'Alice' | 'Bob') {
  useShellStore.setState({
    selectedGameId: '628580',
    gameInfoContext: {
      turn: 10,
      perspectives: [...players],
      isGameFinished: true,
      sectorDisplayName: 'Test Sector',
      stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
    },
    selectedTurn: 5,
    perspectiveOverrideName: viewpointName,
    storageOnlyLoad: false,
    storageAvailablePerspectives: null,
  })
}

function renderTile(overrides: Partial<ComponentProps<typeof FleetAnalyticTile>> = {}) {
  return render(
    <FleetAnalyticTile
      name="Fleet"
      enabled
      supportsMode
      depressed
      onToggle={() => {}}
      {...overrides}
    />
  )
}

describe('FleetAnalyticTile', () => {
  beforeEach(() => {
    useFleetPlayerVisibilityStore.setState({ overrides: {} })
    useShellStore.setState({
      selectedGameId: null,
      gameInfoContext: null,
      selectedTurn: null,
      perspectiveOverrideName: null,
      storageOnlyLoad: false,
      storageAvailablePerspectives: null,
    })
    seedShellViewpoint('Alice')
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
