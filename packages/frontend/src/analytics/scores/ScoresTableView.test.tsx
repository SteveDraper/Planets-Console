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
  it('keeps priority points in the data column when build inference column is appended', () => {
    render(
      <ScoresTableView
        data={tableData({
          columns: [
            'Race (player)',
            'Planets',
            'Starbases',
            'War Ships',
            'Freighters',
            'Military',
            'Priority Points',
            'Build inference',
          ],
          rows: [
            [
              'Federation (alice)',
              '10 (+1)',
              '5',
              '3',
              '2',
              '1000 (-50)',
              '217 (+54)',
            ],
          ],
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

    expect(screen.getByText('217 (+54)')).toBeInTheDocument()
    expect(screen.getByLabelText('Best: one build')).toBeInTheDocument()
  })

  it('renders inference status from inferenceByRow when row has no placeholder cell', () => {
    render(
      <ScoresTableView
        data={tableData({
          columns: ['Race (player)', 'Military', 'Build inference'],
          rows: [['Federation (alice)', '', '', '', '', '100', '']],
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

  it('ignores a legacy trailing empty cell when resolving data column values', () => {
    render(
      <ScoresTableView
        data={tableData({
          columns: ['Race (player)', 'Military', 'Build inference'],
          rows: [['Federation (alice)', '', '', '', '', '100', '']],
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
