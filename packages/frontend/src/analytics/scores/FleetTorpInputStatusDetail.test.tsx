import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FleetTorpInputStatusDetail } from './FleetTorpInputStatusDetail'

describe('FleetTorpInputStatusDetail', () => {
  it('returns null when diagnostics omit fleet torp input status', () => {
    const { container } = render(<FleetTorpInputStatusDetail diagnostics={{}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders section variant with label and belief-set torp ids', () => {
    render(
      <FleetTorpInputStatusDetail
        diagnostics={{
          fleetTorpInputStatus: 'applied',
          fleetTorpOverlay: { beliefSetTorpIds: [4, 8] },
        }}
      />
    )

    expect(screen.getByText('Fleet torpedo overlay input')).toBeInTheDocument()
    expect(screen.getByText(/persisted fleet snapshot/)).toBeInTheDocument()
    expect(screen.getByText('Belief-set torpedo ids: 4, 8')).toBeInTheDocument()
  })

  it('renders inline variant with combined label and belief-set torp ids', () => {
    render(
      <FleetTorpInputStatusDetail
        variant="inline"
        diagnostics={{
          fleetTorpInputStatus: 'applied',
          fleetTorpOverlay: { beliefSetTorpIds: [4, 8] },
        }}
      />
    )

    expect(screen.queryByText('Fleet torpedo overlay input')).toBeNull()
    expect(screen.getByText(/persisted fleet snapshot · Belief-set torpedo ids: 4, 8/)).toBeInTheDocument()
  })
})
