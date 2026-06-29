import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ScoresTableWithInferenceData } from '../../api/bff'
import { ScoresTableView } from './ScoresTableView'

const testScope = {
  gameId: '628580',
  turn: 6,
  perspective: 1,
}

const idleGlobalInferencePause = {
  isGloballyPaused: false,
  isPending: false,
  error: null,
  pauseGlobally: vi.fn(),
  resumeGlobally: vi.fn(),
  syncPausedFromStream: vi.fn(),
}

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
        analyticScope={testScope}
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
        analyticScope={testScope}
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
        analyticScope={testScope}
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

  it('opens inference detail modal when failure icon is clicked', () => {
    render(
      <ScoresTableView
        analyticScope={testScope}
        data={tableData({
          columns: ['Race (player)', 'Build inference'],
          rows: [['Federation (alice)']],
          inferenceByRow: [
            {
              displayStatus: 'failure',
              status: 'no_exact_solution',
              summary: 'No feasible build explanation found',
              solutionCount: 0,
              isComplete: true,
              solutions: [],
              diagnostics: {},
            },
          ],
        })}
      />
    )

    fireEvent.click(screen.getByLabelText('No feasible build explanation found'))
    expect(screen.getByRole('dialog')).toHaveTextContent('No feasible build explanation found')
  })

  it('opens inference detail modal when success icon is clicked', () => {
    render(
      <ScoresTableView
        analyticScope={testScope}
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

  it('shows global pause control beside the build inference column title', () => {
    render(
      <ScoresTableView
        analyticScope={testScope}
        globalInferencePause={idleGlobalInferencePause}
        data={tableData({
          columns: ['Race (player)', 'Build inference'],
          rows: [['Federation (alice)']],
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

    expect(screen.getByLabelText('Pause all build inference for this turn')).toBeInTheDocument()
    expect(screen.queryByLabelText('Resume all build inference for this turn')).toBeNull()
  })

  it('animates the solution count badge while search is ongoing', () => {
    const { container } = render(
      <ScoresTableView
        analyticScope={testScope}
        data={tableData({
          columns: ['Race (player)', 'Build inference'],
          rows: [['Federation (alice)']],
          inferenceByRow: [
            {
              displayStatus: 'success',
              status: 'exact',
              summary: 'Searching: 2 solutions so far',
              solutionCount: 2,
              isComplete: false,
              solutions: [],
              diagnostics: {},
            },
          ],
        })}
      />
    )

    expect(container.querySelector('.inference-border-dot')).not.toBeNull()
    expect(container.querySelector('.border-dashed')).not.toBeNull()
  })

  it('shows dotted zero count for pending rows instead of an hourglass', () => {
    render(
      <ScoresTableView
        analyticScope={testScope}
        data={tableData({
          columns: ['Race (player)', 'Build inference'],
          rows: [['Federation (alice)']],
          inferenceByRow: [
            {
              displayStatus: 'pending',
              status: 'pending',
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

    expect(screen.getByLabelText('Still searching')).toHaveTextContent('0')
    expect(screen.queryByLabelText('Still searching')?.className).toContain('border-dashed')
  })

  it('does not animate incomplete rows while globally paused', () => {
    const { container } = render(
      <ScoresTableView
        analyticScope={testScope}
        isGloballyPaused
        data={tableData({
          columns: ['Race (player)', 'Build inference'],
          rows: [['Federation (alice)']],
          inferenceByRow: [
            {
              displayStatus: 'paused',
              status: 'paused',
              summary: 'Paused with 2 held solution(s)',
              solutionCount: 2,
              isComplete: false,
              solutions: [],
              diagnostics: {},
            },
          ],
        })}
      />
    )

    expect(container.querySelector('.inference-border-dot')).toBeNull()
    expect(screen.getByLabelText('Paused with 2 held solution(s)')).toHaveTextContent('2')
  })

  it('shows dotted zero for paused rows that have not started yet', () => {
    render(
      <ScoresTableView
        analyticScope={testScope}
        isGloballyPaused
        data={tableData({
          columns: ['Race (player)', 'Build inference'],
          rows: [['Federation (alice)']],
          inferenceByRow: [
            {
              displayStatus: 'paused',
              status: 'paused',
              summary: 'Build inference paused',
              solutionCount: 0,
              isComplete: false,
              solutions: [],
              diagnostics: {},
            },
          ],
        })}
      />
    )

    const badge = screen.getByLabelText('Build inference paused')
    expect(badge).toHaveTextContent('0')
    expect(badge.className).toContain('border-dashed')
  })

  it('shows scope banner when any row has pending fleet torp input', () => {
    render(
      <ScoresTableView
        analyticScope={testScope}
        data={tableData({
          columns: ['Race (player)', 'Build inference'],
          rows: [['Federation (alice)', '']],
          inferenceByRow: [
            {
              displayStatus: 'success',
              status: 'exact',
              summary: 'Best: one build',
              solutionCount: 1,
              isComplete: true,
              solutions: [],
              fleetTorpInputStatus: 'pending',
            },
          ],
        })}
      />
    )

    expect(
      screen.getByText(/Prior-turn fleet data is still loading for one player/)
    ).toBeInTheDocument()
    expect(
      screen.getByLabelText(/Best: one build\. Prior-turn fleet torpedo overlay pending/)
    ).toBeInTheDocument()
  })

  it('scrolls the table body in a bounded region with a sticky header row', () => {
    const { container } = render(
      <ScoresTableView
        analyticScope={testScope}
        data={tableData({
          columns: ['Race (player)', 'Military'],
          rows: [['Federation (alice)', '1000']],
          inferenceByRow: [
            {
              displayStatus: 'pending',
              status: 'pending',
              summary: 'Build inference in progress',
              solutionCount: 0,
              isComplete: false,
              solutions: [],
              diagnostics: {},
            },
          ],
        })}
      />
    )

    const scrollRegion = container.querySelector('.overflow-auto')
    expect(scrollRegion).not.toBeNull()
    expect(scrollRegion?.className).toContain('max-h-')

    const header = screen.getByRole('columnheader', { name: 'Race (player)' })
    expect(header.className).toContain('sticky')
    expect(header.className).toContain('top-0')
  })
})
