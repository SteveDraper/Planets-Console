import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ShellErrorBar } from './ShellErrorBar'

describe('ShellErrorBar', () => {
  it('renders nothing when there are no errors', () => {
    const { container } = render(<ShellErrorBar errors={[]} onDismiss={() => {}} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders one row per error with dismiss', async () => {
    const user = userEvent.setup()
    const onDismiss = vi.fn()
    render(
      <ShellErrorBar
        errors={[
          { id: 'a', message: 'First problem' },
          { id: 'b', message: 'Second problem' },
        ]}
        onDismiss={onDismiss}
      />
    )
    expect(screen.getByText('First problem')).toBeInTheDocument()
    expect(screen.getByText('Second problem')).toBeInTheDocument()
    const dismissButtons = screen.getAllByRole('button', { name: /dismiss error/i })
    expect(dismissButtons).toHaveLength(2)
    await user.click(dismissButtons[0])
    expect(onDismiss).toHaveBeenCalledWith('a')
  })
})
