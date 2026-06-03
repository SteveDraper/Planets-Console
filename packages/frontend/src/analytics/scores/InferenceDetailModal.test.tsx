import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ScoresInferenceRowDetail } from '../../api/bff'
import { InferenceDetailModal } from './InferenceDetailModal'

function detail(overrides: Partial<ScoresInferenceRowDetail> = {}): ScoresInferenceRowDetail {
  return {
    displayStatus: 'success',
    status: 'exact',
    summary: 'Best: two defense posts',
    solutionCount: 1,
    isComplete: true,
    solutions: [],
    diagnostics: {},
    ...overrides,
  }
}

describe('InferenceDetailModal', () => {
  it('shows observed constraints and military score arithmetic', () => {
    render(
      <InferenceDetailModal
        isOpen
        onClose={vi.fn()}
        racePlayer="Federation (alice)"
        detail={detail({
          playerId: 5,
          diagnostics: {
            turn: 9,
            constraints: {
              turn: 9,
              playerId: 5,
              militaryDelta2x: 44,
              warshipDelta: 0,
              freighterDelta: 0,
              requestedPriorityPointDelta: 0,
              priorityPointConstraintNote: 'Priority points are diagnostic only',
              appliedEqualities: ['sum(scoreDelta2x * count) == 44'],
            },
            solver: { solver_status: 'OPTIMAL', wall_time_seconds: 0.42 },
          },
          solutions: [
            {
              objectiveValue: 999,
              actions: [
                {
                  actionId: 'planet_defense',
                  label: 'Planet defense post',
                  count: 2,
                },
              ],
              militaryScoreArithmetic: {
                observedMilitaryChange: 22,
                observedMilitaryDelta2x: 44,
                explainedMilitaryChange: 22,
                explainedMilitaryDelta2x: 44,
                matchesObserved: true,
                lineItems: [
                  {
                    actionId: 'planet_defense',
                    label: 'Planet defense post',
                    count: 2,
                    scoreDelta2xPerUnit: 22,
                    militaryChangePerUnit: 11,
                    scoreDelta2xSubtotal: 44,
                    militaryChangeSubtotal: 22,
                  },
                ],
              },
            },
          ],
        })}
      />
    )

    expect(screen.getByRole('dialog')).toHaveTextContent('Federation (alice)')
    expect(screen.getByText('Observed constraints')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toHaveTextContent('Turn 8')
    expect(screen.getByRole('dialog')).toHaveTextContent('Player 5')
    expect(screen.getByText(/Priority points are diagnostic only/)).toBeInTheDocument()
    expect(screen.getByText('Explained military change')).toBeInTheDocument()
    expect(screen.getByText('Planet defense post')).toBeInTheDocument()
    expect(screen.queryByText(/score 999/)).toBeNull()
    expect(screen.queryByText(/score 999/i)).toBeNull()
  })

  it('does not render when closed', () => {
    render(
      <InferenceDetailModal
        isOpen={false}
        onClose={vi.fn()}
        racePlayer="Federation (alice)"
        detail={detail()}
      />
    )
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('calls onClose from the close button', () => {
    const onClose = vi.fn()
    render(
      <InferenceDetailModal
        isOpen
        onClose={onClose}
        racePlayer="Federation (alice)"
        detail={detail()}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledOnce()
  })
})
