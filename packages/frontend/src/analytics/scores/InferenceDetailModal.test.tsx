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

  it('shows negative military change using integer halving of 2× scale', () => {
    render(
      <InferenceDetailModal
        isOpen
        onClose={vi.fn()}
        racePlayer="Federation (alice)"
        detail={detail({
          diagnostics: {
            constraints: {
              militaryDelta2x: -107738,
              warshipDelta: 0,
              freighterDelta: 0,
            },
          },
          solutions: [],
        })}
      />
    )

    expect(screen.getByRole('dialog')).toHaveTextContent('-53869')
    expect(screen.getByRole('dialog')).not.toHaveTextContent('-53869.5')
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

  it('shows accelerated-start segments instead of duplicate top-level solutions', () => {
    render(
      <InferenceDetailModal
        isOpen
        onClose={vi.fn()}
        racePlayer="Federation (alice)"
        detail={detail({
          summary: 'Best: Missouri',
          diagnostics: {
            turn: 3,
            constraints: {
              turn: 3,
              playerId: 1,
              militaryDelta2x: 220,
              warshipDelta: 1,
              freighterDelta: 0,
            },
            accelerated_segments: [
              {
                segmentId: 'accel_window',
                hostTurn: 1,
                status: 'exact',
                solutionCount: 1,
                militaryDelta2x: 220,
                warshipDelta: 0,
                freighterDelta: 0,
                solutions: [
                  {
                    objectiveValue: 999,
                    actions: [
                      {
                        actionId: 'planet_defense',
                        label: 'Planet defense post',
                        count: 10,
                      },
                    ],
                    militaryScoreArithmetic: {
                      observedMilitaryChange: 110,
                      observedMilitaryDelta2x: 220,
                      explainedMilitaryChange: 110,
                      explainedMilitaryDelta2x: 220,
                      matchesObserved: true,
                      lineItems: [
                        {
                          actionId: 'planet_defense',
                          label: 'Planet defense post',
                          count: 10,
                          scoreDelta2xPerUnit: 22,
                          militaryChangePerUnit: 11,
                          scoreDelta2xSubtotal: 220,
                          militaryChangeSubtotal: 110,
                        },
                      ],
                    },
                  },
                ],
              },
              {
                segmentId: 'reported_host_turn',
                hostTurn: 2,
                status: 'exact',
                solutionCount: 1,
                militaryDelta2x: 220,
                warshipDelta: 1,
                freighterDelta: 0,
                solutions: [
                  {
                    objectiveValue: 100,
                    actions: [],
                    militaryScoreArithmetic: {
                      observedMilitaryChange: 110,
                      observedMilitaryDelta2x: 220,
                      explainedMilitaryChange: 110,
                      explainedMilitaryDelta2x: 220,
                      matchesObserved: true,
                      lineItems: [
                        {
                          comboId: 'combo_13_9_3_6_8_6',
                          label: 'Missouri',
                          count: 1,
                          scoreDelta2xPerUnit: 220,
                          militaryChangePerUnit: 110,
                          scoreDelta2xSubtotal: 220,
                          militaryChangeSubtotal: 110,
                        },
                      ],
                    },
                  },
                ],
              },
            ],
          },
          solutions: [
            {
              objectiveValue: 100,
              actions: [],
              militaryScoreArithmetic: {
                observedMilitaryChange: 110,
                observedMilitaryDelta2x: 220,
                explainedMilitaryChange: 110,
                explainedMilitaryDelta2x: 220,
                matchesObserved: true,
                lineItems: [
                  {
                    comboId: 'combo_13_9_3_6_8_6',
                    label: 'Missouri',
                    count: 1,
                    scoreDelta2xPerUnit: 220,
                    militaryChangePerUnit: 110,
                    scoreDelta2xSubtotal: 220,
                    militaryChangeSubtotal: 110,
                  },
                ],
              },
            },
          ],
        })}
      />
    )

    expect(screen.getByText('Accelerated-start game: build inference split by host turn.')).toBeInTheDocument()
    expect(screen.getByText('Host turn 1 (accelerated window)')).toBeInTheDocument()
    expect(screen.getByText('Host turn 2 (on scoreboard row turn 3)')).toBeInTheDocument()
    expect(screen.getByText('Planet defense post')).toBeInTheDocument()
    expect(screen.getByText('Missouri')).toBeInTheDocument()
    expect(screen.getByText('Scoreboard row constraints')).toBeInTheDocument()
    expect(screen.queryAllByText('Solution 1')).toHaveLength(2)
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
