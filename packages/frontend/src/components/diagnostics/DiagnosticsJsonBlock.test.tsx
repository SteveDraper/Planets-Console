import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { CollapsibleJsonView } from './DiagnosticsJsonBlock'

describe('CollapsibleJsonView', () => {
  it('renders nested objects with collapsible sections', async () => {
    const user = userEvent.setup()
    render(
      <CollapsibleJsonView
        value={{
          constraints: {
            militaryDelta2x: -107738,
            appliedEqualities: ['sum(scoreDelta2x * count) == -107738'],
          },
          actions: [{ id: 'planet_defense_posts_added_total' }],
        }}
      />
    )

    expect(screen.getByText(/constraints:/)).toBeTruthy()
    expect(screen.getByText(/militaryDelta2x:/)).toBeTruthy()

    const rootToggle = screen.getAllByRole('button', { name: /\{2\}/ })[0]
    await user.click(rootToggle)
    expect(screen.queryByText(/militaryDelta2x:/)).toBeNull()

    await user.click(rootToggle)
    expect(screen.getByText(/militaryDelta2x:/)).toBeTruthy()
  })
})
