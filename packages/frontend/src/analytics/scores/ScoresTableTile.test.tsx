import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ScoresTableTile } from './ScoresTableTile'

describe('ScoresTableTile', () => {
  it('shows include build inference checkbox when scores is enabled in tabular mode', () => {
    const onScoresTableParamsChange = vi.fn()
    render(
      <ScoresTableTile
        name="Scores"
        enabled
        supportsMode
        depressed
        onToggle={() => {}}
        scoresTableParams={{ includeBuildInference: false }}
        onScoresTableParamsChange={onScoresTableParamsChange}
        buildInferenceAvailable
      />
    )

    const inferenceCheckbox = screen.getByLabelText('Include build inference')
    fireEvent.click(inferenceCheckbox)
    expect(onScoresTableParamsChange).toHaveBeenCalledWith({ includeBuildInference: true })
  })

  it('hides include build inference checkbox when scores is disabled', () => {
    render(
      <ScoresTableTile
        name="Scores"
        enabled={false}
        supportsMode
        depressed={false}
        onToggle={() => {}}
        scoresTableParams={{ includeBuildInference: false }}
        onScoresTableParamsChange={() => {}}
      />
    )

    expect(screen.queryByLabelText('Include build inference')).toBeNull()
  })

  it('grey-disables include build inference when availability is off', () => {
    render(
      <ScoresTableTile
        name="Scores"
        enabled
        supportsMode
        depressed
        onToggle={() => {}}
        scoresTableParams={{ includeBuildInference: true }}
        onScoresTableParamsChange={() => {}}
        buildInferenceAvailable={false}
      />
    )

    const inferenceCheckbox = screen.getByLabelText('Include build inference')
    expect(inferenceCheckbox).toBeDisabled()
    expect(inferenceCheckbox).toHaveAttribute(
      'title',
      expect.stringMatching(/stealth mode/i)
    )
  })

  it('keeps include build inference disabled until availability is known', () => {
    render(
      <ScoresTableTile
        name="Scores"
        enabled
        supportsMode
        depressed
        onToggle={() => {}}
        scoresTableParams={{ includeBuildInference: false }}
        onScoresTableParamsChange={() => {}}
      />
    )

    const inferenceCheckbox = screen.getByLabelText('Include build inference')
    expect(inferenceCheckbox).toBeDisabled()
    expect(inferenceCheckbox).not.toHaveAttribute('title')
  })
})
