import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { HomeworldLocatorTile } from './HomeworldLocatorTile'

describe('HomeworldLocatorTile', () => {
  it('disables the toggle and shows an inactive hint when unavailable', () => {
    render(
      <ul>
        <HomeworldLocatorTile
          name="Homeworld locator"
          enabled={false}
          supportsMode
          depressed={false}
          onToggle={() => undefined}
          inactiveReason="nohomeworld"
        />
      </ul>
    )
    const checkbox = screen.getByRole('checkbox')
    expect(checkbox).toBeDisabled()
    expect(screen.getByTitle(/no homeworld planets/i)).toBeInTheDocument()
  })

  it('allows enabling when available and mode is supported', () => {
    render(
      <ul>
        <HomeworldLocatorTile
          name="Homeworld locator"
          enabled={false}
          supportsMode
          depressed={false}
          onToggle={() => undefined}
          inactiveReason={null}
        />
      </ul>
    )
    expect(screen.getByRole('checkbox')).not.toBeDisabled()
  })
})
