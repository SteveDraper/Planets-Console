import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ScoresTableWithInferenceData } from '../../api/bff'
import { ScoresTableView } from './ScoresTableView'

function tableData(
  overrides: Partial<ScoresTableWithInferenceData> &
    Pick<ScoresTableWithInferenceData, 'columns' | 'rows' | 'inferenceByRow'>
): ScoresTableWithInferenceData {
  return {
    analyticId: 'scores',
    includeBuildInference: true,
    ...overrides,
  }
}

describe('ScoresTableView', () => {
  it('renders inference status from inferenceByRow when row has no placeholder cell', () => {
    render(
      <ScoresTableView
        data={tableData({
          columns: ['Race (player)', 'Military', 'Build inference'],
          rows: [['Federation (alice)', '100']],
          inferenceByRow: [
            {
              displayStatus: 'success',
              status: 'exact',
              summary: 'Best: one build',
              solutionCount: 1,
              isComplete: true,
              solutions: [],
              diagnostics: {},
            },
          ],
        })}
      />
    )

    expect(screen.getByLabelText('Best: one build')).toBeInTheDocument()
    expect(screen.getByText('100')).toBeInTheDocument()
  })

  it('renders inference icons from inferenceByRow even when a legacy row has a trailing empty cell', () => {
    render(
      <ScoresTableView
        data={tableData({
          columns: ['Race (player)', 'Military', 'Build inference'],
          rows: [['Federation (alice)', '100', '']],
          inferenceByRow: [
            {
              displayStatus: 'pending',
              status: 'time_limited',
              summary: 'Still searching',
              solutionCount: 0,
              isComplete: false,
              solutions: [],
              diagnostics: {},
            },
          ],
        })}
      />
    )

    expect(screen.getByLabelText('Still searching')).toBeInTheDocument()
    expect(screen.getByText('100')).toBeInTheDocument()
  })

  it('opens inference detail modal when success icon is clicked', () => {
    render(
      <ScoresTableView
        data={tableData({
          columns: ['Race (player)', 'Build inference'],
          rows: [['Federation (alice)']],
          inferenceByRow: [
            {
              displayStatus: 'success',
              status: 'exact',
              summary: 'Best: one build',
              solutionCount: 1,
              isComplete: true,
              solutions: [{ objectiveValue: 1, actions: [] }],
              diagnostics: {},
            },
          ],
        })}
      />
    )

    fireEvent.click(screen.getByLabelText('Best: one build'))
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('Federation (alice)')
    expect(dialog).toHaveTextContent('Solution 1')
  })
})
