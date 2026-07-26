import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { defaultHomeworldRegionDisplayMode } from './homeworldRegionDisplayMode'
import { HomeworldLocatorTile } from './HomeworldLocatorTile'
import {
  HOMEWORLD_REGION_DISPLAY_STORAGE_KEY,
  useHomeworldRegionDisplayStore,
} from '../../stores/homeworldRegionDisplay'

describe('HomeworldLocatorTile', () => {
  beforeEach(() => {
    localStorage.removeItem(HOMEWORLD_REGION_DISPLAY_STORAGE_KEY)
    useHomeworldRegionDisplayStore.setState({
      regionDisplayMode: defaultHomeworldRegionDisplayMode(),
    })
  })

  it('disables the toggle and shows an inactive hint when unavailable', () => {
    render(
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
    render(
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
    render(
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

  it('expands to expose region display mode and persists changes', async () => {
    const user = userEvent.setup()
    render(
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
    expect(screen.getByRole('radiogroup', { name: /homeworld region display mode/i })).toBeInTheDocument()

    await user.click(screen.getByRole('radio', { name: 'All' }))
    expect(useHomeworldRegionDisplayStore.getState().regionDisplayMode).toBe('all')
    expect(localStorage.getItem(HOMEWORLD_REGION_DISPLAY_STORAGE_KEY)).toContain('all')
  })
})
