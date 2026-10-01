import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AnalyticSidebarTile, analyticEnableCheckboxClassName } from './AnalyticSidebarTile'

const base = {
  name: 'Example',
  enabled: true,
  supportsMode: true,
  depressed: true,
  onToggle: vi.fn(),
}

describe('AnalyticSidebarTile', () => {
  it('uses the shared enable-checkbox accent and omits the chevron when there are no details', () => {
    render(<AnalyticSidebarTile {...base} />)
    const checkbox = screen.getByRole('checkbox', { name: 'Example' })
    expect(checkbox).toHaveClass(...analyticEnableCheckboxClassName.split(' '))
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('keeps details collapsed until the chevron is used', async () => {
    const user = userEvent.setup()
    render(
      <AnalyticSidebarTile {...base} detailsLabel="Example options">
        <span>Owned planets only</span>
      </AnalyticSidebarTile>
    )
    expect(screen.queryByText('Owned planets only')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Expand Example options' }))
    expect(screen.getByText('Owned planets only')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Collapse Example options' }))
    expect(screen.queryByText('Owned planets only')).not.toBeInTheDocument()
  })

  it('closes the pane when the row can no longer expand, and stays closed when it can again', async () => {
    const user = userEvent.setup()
    const details = (
      <AnalyticSidebarTile {...base} detailsLabel="Example options">
        <span>Owned planets only</span>
      </AnalyticSidebarTile>
    )
    const { rerender } = render(details)
    await user.click(screen.getByRole('button', { name: 'Expand Example options' }))
    expect(screen.getByText('Owned planets only')).toBeInTheDocument()

    rerender(
      <AnalyticSidebarTile {...base} enabled={false} depressed={false} detailsLabel="Example options">
        <span>Owned planets only</span>
      </AnalyticSidebarTile>
    )
    expect(screen.queryByText('Owned planets only')).not.toBeInTheDocument()

    rerender(details)
    expect(screen.queryByText('Owned planets only')).not.toBeInTheDocument()
  })

  it('disables the enable checkbox and the chevron when the row cannot be toggled', () => {
    render(
      <AnalyticSidebarTile {...base} supportsMode={false} depressed={false} detailsLabel="Example options">
        <span>Owned planets only</span>
      </AnalyticSidebarTile>
    )
    const checkbox = screen.getByRole('checkbox', { name: 'Example' })
    expect(checkbox).toBeDisabled()
    expect(checkbox).toBeChecked()
    expect(screen.getByRole('button', { name: 'Expand Example options' })).toBeDisabled()
    expect(screen.queryByText('Owned planets only')).not.toBeInTheDocument()
  })

  it('greys the row when the analytic is inactive for this game', () => {
    const { container } = render(
      <AnalyticSidebarTile {...base} available={false} hint="This game has no minefields" detailsLabel="types">
        <span>Normal</span>
      </AnalyticSidebarTile>
    )
    const checkbox = screen.getByRole('checkbox', { name: 'Example' })
    expect(container.firstChild).toHaveClass('opacity-50')
    expect(checkbox).toBeDisabled()
    expect(checkbox).toBeChecked()
    expect(container.firstChild).toHaveAttribute('title', 'This game has no minefields')
  })
})
