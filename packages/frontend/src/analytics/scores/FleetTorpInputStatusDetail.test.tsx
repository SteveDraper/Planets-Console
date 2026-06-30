import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ScoresInferenceRowDetail } from '../../api/bff'
import { FleetTorpInputStatusDetail } from './FleetTorpInputStatusDetail'

function detail(
  overrides: Partial<ScoresInferenceRowDetail> = {}
): ScoresInferenceRowDetail {
  return {
    displayStatus: 'success',
    status: 'exact',
    summary: 'Best: one build',
    solutionCount: 1,
    isComplete: true,
    solutions: [],
    diagnostics: {},
    ...overrides,
  }
}

describe('FleetTorpInputStatusDetail', () => {
  it('returns null when detail omits fleet torp input status', () => {
    const { container } = render(<FleetTorpInputStatusDetail detail={detail()} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders section variant with label and belief-set torp ids', () => {
    render(
      <FleetTorpInputStatusDetail
        detail={detail({
          fleetTorpInputStatus: 'applied',
          fleetTorpOverlayBeliefSetTorpIds: [4, 8],
        })}
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
        detail={detail({
          fleetTorpInputStatus: 'applied',
          fleetTorpOverlayBeliefSetTorpIds: [4, 8],
        })}
      />
    )

    expect(screen.queryByText('Fleet torpedo overlay input')).toBeNull()
    expect(screen.getByText(/persisted fleet snapshot · Belief-set torpedo ids: 4, 8/)).toBeInTheDocument()
  })
})
