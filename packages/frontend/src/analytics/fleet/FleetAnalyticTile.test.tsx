import { beforeEach, describe, expect, it } from 'vitest'
import type { ComponentProps } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FleetAnalyticTile } from './FleetAnalyticTile'
import { useFleetPlayerVisibilityStore } from '../../stores/fleetPlayerVisibility'

const players = [
  { ordinal: 1, playerId: 8, name: 'Alice', raceName: null },
  { ordinal: 2, playerId: 9, name: 'Bob', raceName: null },
] as const

function renderTile(overrides: Partial<ComponentProps<typeof FleetAnalyticTile>> = {}) {
  return render(
    <FleetAnalyticTile
      name="Fleet"
      enabled
      supportsMode
      depressed
      onToggle={() => {}}
      players={[...players]}
      viewpointPlayerId={8}
      {...overrides}
    />
  )
}

describe('FleetAnalyticTile', () => {
  beforeEach(() => {
    useFleetPlayerVisibilityStore.setState({ overrides: {} })
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

  it('persists player toggle changes through the visibility store', async () => {
    const user = userEvent.setup()
    renderTile()
    await user.click(screen.getByLabelText('Expand Fleet player visibility'))
    await user.click(screen.getByLabelText('Bob'))
    expect(useFleetPlayerVisibilityStore.getState().isFleetPlayerVisible(9, 8)).toBe(false)
  })
})
