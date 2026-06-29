import { act, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ScoresInferenceRowDetail } from '../../api/bff'
import { FleetTorpInputStatusAnnouncer } from './FleetTorpInputStatusAnnouncer'
import { fleetTorpInputAccessibleLabel } from './fleetTorpInputStatus'

function flushAnimationFrame(): Promise<void> {
  return new Promise((resolve) => {
    requestAnimationFrame(() => resolve())
  })
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
    render(<FleetTorpInputStatusAnnouncer inferenceByRow={[]} />)
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
        inferenceByRow={[
          inferenceRow({
            playerId: 1,
            diagnostics: { fleetTorpInputStatus: 'not_applicable' },
          }),
        ]}
      />
    )

    rerender(
      <FleetTorpInputStatusAnnouncer
        inferenceByRow={[
          inferenceRow({ playerId: 1, diagnostics: { fleetTorpInputStatus: 'pending' } }),
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
        inferenceByRow={[
          inferenceRow({ playerId: 1, diagnostics: { fleetTorpInputStatus: 'pending' } }),
        ]}
      />
    )

    await act(async () => {
      await flushAnimationFrame()
    })

    rerender(
      <FleetTorpInputStatusAnnouncer
        inferenceByRow={[
          inferenceRow({ playerId: 1, diagnostics: { fleetTorpInputStatus: 'applied' } }),
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
    const row = inferenceRow({ playerId: 1, diagnostics: { fleetTorpInputStatus: 'pending' } })
    const { rerender } = render(<FleetTorpInputStatusAnnouncer inferenceByRow={[row]} />)

    await act(async () => {
      await flushAnimationFrame()
    })
    const region = screen.getByRole('status')
    expect(region).toHaveTextContent(pendingLabel)

    rerender(<FleetTorpInputStatusAnnouncer inferenceByRow={[{ ...row }]} />)

    await act(async () => {
      await flushAnimationFrame()
    })

    expect(region).toHaveTextContent(pendingLabel)
  })

  it('ignores rows without playerId', async () => {
    render(
      <FleetTorpInputStatusAnnouncer
        inferenceByRow={[
          inferenceRow({ diagnostics: { fleetTorpInputStatus: 'pending' } }),
        ]}
      />
    )

    await act(async () => {
      await flushAnimationFrame()
    })

    expect(screen.getByRole('status')).toHaveTextContent('')
  })
})
