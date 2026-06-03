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
})
