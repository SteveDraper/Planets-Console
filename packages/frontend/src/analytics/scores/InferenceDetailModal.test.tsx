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

const defenseSolution = {
  objectiveValue: 999,
  actions: [
    {
      actionId: 'planet_defense_posts_added_total',
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
        actionId: 'planet_defense_posts_added_total',
        label: 'Planet defense post',
        count: 2,
        scoreDelta2xPerUnit: 22,
        militaryChangePerUnit: 11,
        scoreDelta2xSubtotal: 44,
        militaryChangeSubtotal: 22,
      },
    ],
  },
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
          solutions: [defenseSolution],
        })}
      />
    )

    expect(screen.getByRole('dialog')).toHaveTextContent('Federation (alice)')
    expect(screen.getByText('Observed constraints')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toHaveTextContent('Scoreboard row turn 9')
    expect(screen.getByRole('dialog')).toHaveTextContent('Host turn 8 deltas')
    expect(screen.getByRole('dialog')).toHaveTextContent('Player 5')
    // PP note and spectator delta-source note belong in Scores diagnostics panel, not modal (#48 UX).
    expect(screen.queryByText(/Priority points are diagnostic only/)).toBeNull()
    expect(screen.queryByText(/Change columns were missing/)).toBeNull()
    expect(screen.getByText('Solution 1 · Plausibility 999')).toBeInTheDocument()
    expect(screen.getByText('Planet defense post (2)')).toBeInTheDocument()
    expect(screen.getByText('Explained military change')).toBeInTheDocument()
    expect(screen.getByText('Observed military change')).toBeInTheDocument()
    expect(screen.queryByText('Best: two defense posts')).toBeNull()
    expect(screen.queryByText(/2× scale/)).toBeNull()
    expect(screen.queryByText(/appliedEqualities|scoreDelta2x \* count/)).toBeNull()
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
    expect(screen.getByRole('dialog')).not.toHaveTextContent('2× scale')
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

  it('renders top-level solutions only when accelerated segments are present in diagnostics', () => {
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
                    actions: [],
                    militaryScoreArithmetic: {
                      observedMilitaryChange: 110,
                      lineItems: [
                        {
                          actionId: 'planet_defense_posts_added_total',
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
            ],
          },
          solutions: [
            {
              objectiveValue: 100,
              actions: [],
              shipBuilds: [
                {
                  comboId: 'combo_13_9_3_6_8_6',
                  label: 'Missouri',
                  count: 1,
                  hullId: 13,
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

    expect(screen.queryByText(/Accelerated-start game/)).toBeNull()
    expect(screen.queryByText('Host turn 1 (accelerated window)')).toBeNull()
    expect(screen.getByText('Solution 1 · Plausibility 100')).toBeInTheDocument()
    expect(screen.getByText('Missouri')).toBeInTheDocument()
    const hullImage = screen.getByRole('dialog').querySelector(
      'img[src="https://mobile.planets.nu/img/hulls3d/13_p.png"]'
    )
    expect(hullImage).not.toBeNull()
  })

  it('shows reconciliation warning when explained military does not match observed', () => {
    render(
      <InferenceDetailModal
        isOpen
        onClose={vi.fn()}
        racePlayer="Federation (alice)"
        detail={detail({
          solutions: [
            {
              ...defenseSolution,
              militaryScoreArithmetic: {
                ...defenseSolution.militaryScoreArithmetic,
                explainedMilitaryChange: 20,
                matchesObserved: false,
              },
            },
          ],
        })}
      />
    )

    expect(
      screen.getByText(/Explained military change does not match the observed scoreboard delta/)
    ).toBeInTheDocument()
  })

  it('shows continuing banner while search is in flight', () => {
    render(
      <InferenceDetailModal
        isOpen
        onClose={vi.fn()}
        racePlayer="Federation (alice)"
        detail={detail({
          isComplete: false,
          solutions: [defenseSolution],
        })}
      />
    )

    expect(
      screen.getByText('Search continuing -- more explanations may appear.')
    ).toBeInTheDocument()
    expect(
      screen.queryByText(/stopped before all alternatives were explored/)
    ).toBeNull()
  })

  it('shows paused banner when row or global pause is active', () => {
    const { rerender } = render(
      <InferenceDetailModal
        isOpen
        onClose={vi.fn()}
        racePlayer="Federation (alice)"
        detail={detail({
          displayStatus: 'paused',
          isComplete: false,
          solutions: [defenseSolution],
        })}
      />
    )
    expect(
      screen.getByText('Search paused -- held explanations are current.')
    ).toBeInTheDocument()

    rerender(
      <InferenceDetailModal
        isOpen
        onClose={vi.fn()}
        racePlayer="Federation (alice)"
        isGloballyPaused
        detail={detail({
          isComplete: false,
          solutions: [defenseSolution],
        })}
      />
    )
    expect(
      screen.getByText('Search paused -- held explanations are current.')
    ).toBeInTheDocument()
  })

  it('shows overall inference status instead of the last solver pass status', () => {
    render(
      <InferenceDetailModal
        isOpen
        onClose={vi.fn()}
        racePlayer="Crystal (koski)"
        detail={detail({
          status: 'exact',
          solutionCount: 2,
          summary: 'Best: Ruby cruiser; 1 alternative',
          diagnostics: {
            solver: {
              status: 'exact',
              solver_status: 'INFEASIBLE',
              wall_time_seconds: 0.12,
              stopped_reason: 'infeasible',
            },
          },
          solutions: [{ objectiveValue: 85, actions: [] }, { objectiveValue: 80, actions: [] }],
        })}
      />
    )

    expect(screen.getByRole('dialog')).toHaveTextContent('Inference exact · 0.12s')
    expect(screen.getByRole('dialog')).not.toHaveTextContent('INFEASIBLE')
    expect(screen.getByText('Solution 1 · Plausibility 85')).toBeInTheDocument()
    expect(screen.getByText('Solution 2 · Plausibility 80')).toBeInTheDocument()
  })

  it('shows fleet torpedo overlay input status and belief set torp ids', () => {
    render(
      <InferenceDetailModal
        isOpen
        onClose={vi.fn()}
        racePlayer="Federation (alice)"
        detail={detail({
          fleetTorpInputStatus: 'applied',
          fleetTorpOverlayBeliefSetTorpIds: [4, 8],
        })}
      />
    )

    expect(screen.getByText('Fleet torpedo overlay input')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toHaveTextContent('persisted fleet snapshot')
    expect(screen.getByRole('dialog')).toHaveTextContent('Belief-set torpedo ids: 4, 8')
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
