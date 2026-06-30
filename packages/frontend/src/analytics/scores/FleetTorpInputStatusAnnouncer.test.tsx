import { act, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { AnalyticShellScope, ScoresInferenceRowDetail } from '../../api/bff'
import { FleetTorpInputStatusAnnouncer } from './FleetTorpInputStatusAnnouncer'
import { fleetTorpInputAccessibleLabel } from './fleetTorpInputStatus'

function flushAnimationFrame(): Promise<void> {
  return new Promise((resolve) => {
    requestAnimationFrame(() => resolve())
  })
}

const scopeA: AnalyticShellScope = {
  gameId: '628580',
  turn: 3,
  perspective: 1,
}

const scopeB: AnalyticShellScope = {
  gameId: '628580',
  turn: 4,
  perspective: 1,
}

function inferenceRow(
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

describe('FleetTorpInputStatusAnnouncer', () => {
  it('always mounts an aria-live status region', () => {
    render(<FleetTorpInputStatusAnnouncer analyticScope={scopeA} inferenceByRow={[]} />)
    const region = screen.getByRole('status')
    expect(region).toHaveAttribute('aria-live', 'polite')
    expect(region).toHaveAttribute('aria-atomic', 'true')
    expect(region).toHaveClass('sr-only')
    expect(region).toHaveTextContent('')
  })

  it('announces when a row becomes pending', async () => {
    const pendingLabel = fleetTorpInputAccessibleLabel('pending')
    const { rerender } = render(
      <FleetTorpInputStatusAnnouncer
        analyticScope={scopeA}
        inferenceByRow={[
          inferenceRow({
            playerId: 1,
            fleetTorpInputStatus: 'not_applicable',
          }),
        ]}
      />
    )

    rerender(
      <FleetTorpInputStatusAnnouncer
        analyticScope={scopeA}
        inferenceByRow={[
          inferenceRow({ playerId: 1, fleetTorpInputStatus: 'pending' }),
        ]}
      />
    )

    await act(async () => {
      await flushAnimationFrame()
    })

    expect(screen.getByRole('status')).toHaveTextContent(pendingLabel)
  })

  it('announces pending to applied transition', async () => {
    const appliedLabel = fleetTorpInputAccessibleLabel('applied')
    const { rerender } = render(
      <FleetTorpInputStatusAnnouncer
        analyticScope={scopeA}
        inferenceByRow={[
          inferenceRow({ playerId: 1, fleetTorpInputStatus: 'pending' }),
        ]}
      />
    )

    await act(async () => {
      await flushAnimationFrame()
    })

    rerender(
      <FleetTorpInputStatusAnnouncer
        analyticScope={scopeA}
        inferenceByRow={[
          inferenceRow({ playerId: 1, fleetTorpInputStatus: 'applied' }),
        ]}
      />
    )

    await act(async () => {
      await flushAnimationFrame()
    })

    expect(screen.getByRole('status')).toHaveTextContent(appliedLabel)
  })

  it('does not announce again when status is unchanged', async () => {
    const pendingLabel = fleetTorpInputAccessibleLabel('pending')
    const row = inferenceRow({ playerId: 1, fleetTorpInputStatus: 'pending' })
    const { rerender } = render(
      <FleetTorpInputStatusAnnouncer analyticScope={scopeA} inferenceByRow={[row]} />
    )

    await act(async () => {
      await flushAnimationFrame()
    })
    const region = screen.getByRole('status')
    expect(region).toHaveTextContent(pendingLabel)

    rerender(<FleetTorpInputStatusAnnouncer analyticScope={scopeA} inferenceByRow={[{ ...row }]} />)

    await act(async () => {
      await flushAnimationFrame()
    })

    expect(region).toHaveTextContent(pendingLabel)
  })

  it('isolates transition memory per analytic scope', async () => {
    const pendingLabel = fleetTorpInputAccessibleLabel('pending')
    const appliedLabel = fleetTorpInputAccessibleLabel('applied')
    const pendingRow = inferenceRow({
      playerId: 1,
      fleetTorpInputStatus: 'pending',
    })
    const appliedRow = inferenceRow({
      playerId: 1,
      fleetTorpInputStatus: 'applied',
    })
    const { rerender } = render(
      <FleetTorpInputStatusAnnouncer analyticScope={scopeA} inferenceByRow={[pendingRow]} />
    )

    await act(async () => {
      await flushAnimationFrame()
    })
    expect(screen.getByRole('status')).toHaveTextContent(pendingLabel)

    rerender(
      <FleetTorpInputStatusAnnouncer analyticScope={scopeB} inferenceByRow={[appliedRow]} />
    )

    await act(async () => {
      await flushAnimationFrame()
    })

    expect(screen.getByRole('status')).toHaveTextContent(pendingLabel)

    rerender(
      <FleetTorpInputStatusAnnouncer analyticScope={scopeB} inferenceByRow={[pendingRow]} />
    )

    await act(async () => {
      await flushAnimationFrame()
    })

    expect(screen.getByRole('status')).toHaveTextContent(pendingLabel)
    expect(screen.getByRole('status')).not.toHaveTextContent(appliedLabel)
  })

  it('announces scope-level pending when any row becomes pending', async () => {
    const pendingLabel = fleetTorpInputAccessibleLabel('pending')
    const { rerender } = render(
      <FleetTorpInputStatusAnnouncer
        analyticScope={scopeA}
        inferenceByRow={[
          inferenceRow({ playerId: 1, fleetTorpInputStatus: 'applied' }),
          inferenceRow({ playerId: 2, fleetTorpInputStatus: 'not_applicable' }),
        ]}
      />
    )

    rerender(
      <FleetTorpInputStatusAnnouncer
        analyticScope={scopeA}
        inferenceByRow={[
          inferenceRow({ playerId: 1, fleetTorpInputStatus: 'applied' }),
          inferenceRow({ playerId: 2, fleetTorpInputStatus: 'pending' }),
        ]}
      />
    )

    await act(async () => {
      await flushAnimationFrame()
    })

    expect(screen.getByRole('status')).toHaveTextContent(pendingLabel)
  })

  it('ignores rows without playerId', async () => {
    render(
      <FleetTorpInputStatusAnnouncer
        analyticScope={scopeA}
        inferenceByRow={[
          inferenceRow({ fleetTorpInputStatus: 'pending' }),
        ]}
      />
    )

    await act(async () => {
      await flushAnimationFrame()
    })

    expect(screen.getByRole('status')).toHaveTextContent('')
  })
})
