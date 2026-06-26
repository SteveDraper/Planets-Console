import { beforeEach, describe, expect, it } from 'vitest'
import type { ComponentProps } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FleetAnalyticTile } from './FleetAnalyticTile'
import { seedShellViewpoint } from './fleetTestShell'
import { useFleetPlayerVisibilityStore } from '../../stores/fleetPlayerVisibility'
import { useShellStore } from '../../stores/shell'

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
