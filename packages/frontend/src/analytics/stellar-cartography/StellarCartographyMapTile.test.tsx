import { beforeEach, describe, expect, it } from 'vitest'
import type { ComponentProps } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StellarCartographyMapTile } from './StellarCartographyMapTile'
import { defaultCartographyLayerVisibility } from './layers'
import { defaultWormholeDisplayMode } from './wormholeDisplayMode'
import { useStellarCartographyLayersStore } from '../../stores/stellarCartographyLayers'

const allGatesEnabled = {
  debrisDiskBorders: true,
  starClusters: true,
  nebulae: true,
  ionStorms: true,
  wormholes: true,
  blackHoles: true,
}

function renderTile(
  overrides: Partial<ComponentProps<typeof StellarCartographyMapTile>> = {}
) {
  return render(
    <StellarCartographyMapTile
      name="Stellar Cartography"
      enabled
      supportsMode
      depressed
      onToggle={() => {}}
      settingsGates={allGatesEnabled}
      ionStormCount={3}
      {...overrides}
    />
  )
}

describe('StellarCartographyMapTile', () => {
  beforeEach(() => {
    useStellarCartographyLayersStore.setState({
      layers: defaultCartographyLayerVisibility(),
      wormholeDisplayMode: defaultWormholeDisplayMode(),
    })
  })

  it('hides layer checkboxes until expanded', () => {
    renderTile()
    expect(screen.queryByLabelText('Nebulae')).not.toBeInTheDocument()
  })

  it('shows only settings-gated layers when expanded', async () => {
    const user = userEvent.setup()
    renderTile({
      settingsGates: {
        debrisDiskBorders: false,
        starClusters: true,
        nebulae: false,
        ionStorms: true,
        wormholes: false,
        blackHoles: true,
      },
    })
    await user.click(
      screen.getByRole('button', { name: /expand stellar cartography layers/i })
    )
    expect(screen.getByText('Star clusters')).toBeInTheDocument()
    expect(screen.queryByText('Nebulae')).not.toBeInTheDocument()
    expect(screen.getByText('Ion storms')).toBeInTheDocument()
    expect(screen.queryByText('Wormholes')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Wormhole display mode')).not.toBeInTheDocument()
    expect(screen.getByText('Black holes')).toBeInTheDocument()
  })

  it('renders wormhole display mode control when the settings gate is enabled', async () => {
    const user = userEvent.setup()
    renderTile()
    await user.click(
      screen.getByRole('button', { name: /expand stellar cartography layers/i })
    )
    expect(screen.getByRole('radiogroup', { name: 'Wormhole display mode' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'Always' })).toHaveAttribute('aria-checked', 'true')
  })

  it('disables ion storms layer when turn has no storms', async () => {
    const user = userEvent.setup()
    renderTile({ ionStormCount: 0 })
    await user.click(
      screen.getByRole('button', { name: /expand stellar cartography layers/i })
    )
    const ionStorms = screen.getByText('Ion storms').closest('label')
    expect(ionStorms).toHaveAttribute('title', 'No ion storms on this turn')
    expect(screen.getByRole('checkbox', { name: /ion storms/i })).toBeDisabled()
  })

  it('persists layer toggle changes through the store', async () => {
    const user = userEvent.setup()
    renderTile()
    await user.click(
      screen.getByRole('button', { name: /expand stellar cartography layers/i })
    )
    await user.click(screen.getByRole('checkbox', { name: /nebulae/i }))
    expect(useStellarCartographyLayersStore.getState().isLayerEnabled('nebulae')).toBe(false)
  })
})
