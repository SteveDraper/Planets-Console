import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MapPaneWithDisplayControls } from './MapPaneWithDisplayControls'

describe('MapPaneWithDisplayControls', () => {
  it('opens and closes the map options panel without removing the map', async () => {
    const user = userEvent.setup()
    render(
      <div className="flex h-[320px] flex-col">
        <MapPaneWithDisplayControls>
          <div>stub map</div>
        </MapPaneWithDisplayControls>
      </div>
    )

    expect(screen.getByText('stub map')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /show map options/i }))
    expect(screen.getByRole('heading', { name: /map options/i })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /hide map options/i }))
    expect(screen.getByRole('button', { name: /show map options/i })).toBeVisible()
  })
})
