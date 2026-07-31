import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ShellCenterPane, ShellErrorPane } from './ShellPlaceholders'

describe('ShellPlaceholders', () => {
  it('ShellCenterPane fills the main content flex slot without a width cap', () => {
    const { container } = render(<ShellCenterPane message="Loading…" />)
    const pane = container.querySelector('main')
    expect(pane).toHaveClass('flex-1', 'min-w-0')
    expect(pane).not.toHaveClass('max-w-3xl')
    expect(screen.getByText('Loading…')).toBeInTheDocument()
  })

  it('ShellErrorPane fills the content area and caps text inside, not the pane', () => {
    const longDetail = [
      'Map: TypeError: Failed to fetch - GET /bff/analytics/base-map/map?game_id=1',
      'Connections: TypeError: Failed to fetch - GET /bff/analytics/connections/map?game_id=1',
    ].join('\n')

    const { container } = render(
      <ShellErrorPane title="Failed to load map data" error={new Error(longDetail)} />
    )

    const pane = container.querySelector('main')
    expect(pane).toHaveClass('flex-1', 'min-w-0', 'overflow-auto')
    expect(pane).not.toHaveClass('max-w-3xl')

    const textBox = pane?.firstElementChild
    expect(textBox).toHaveClass('w-full', 'max-w-3xl', 'min-w-0')

    expect(screen.getByText('Failed to load map data')).toBeInTheDocument()
    expect(screen.getByText(/base-map\/map/)).toBeInTheDocument()
  })
})
