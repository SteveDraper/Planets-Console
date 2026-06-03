import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { LoadAllProgressUpdate } from '../api/bff'
import { ShellLoadAllProgressBar } from './ShellLoadAllProgressBar'

function progress(overrides: Partial<LoadAllProgressUpdate> = {}): LoadAllProgressUpdate {
  return {
    phase: 'import',
    perspective: 2,
    perspective_total: 5,
    turn: 10,
    turn_total: 20,
    message: 'Perspective 2, turn 10',
    ...overrides,
  }
}

function phaseMessage(text: string) {
  return (_content: string, element: Element | null) =>
    element?.tagName === 'P' && element.textContent === text
}

describe('ShellLoadAllProgressBar', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders dual progress bars and counts', () => {
    render(<ShellLoadAllProgressBar progress={progress()} />)
    expect(screen.getByText('Perspectives')).toBeInTheDocument()
    expect(screen.getByText('Turns')).toBeInTheDocument()
    expect(screen.getByText('2 / 5')).toBeInTheDocument()
    expect(screen.getByText('10 / 20')).toBeInTheDocument()
    expect(screen.getByText(phaseMessage('Perspective 2, turn 10.'))).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Perspective progress' })).toHaveAttribute(
      'aria-valuenow',
      '40'
    )
    expect(
      screen.getByRole('progressbar', { name: 'Turn progress within perspective' })
    ).toHaveAttribute('aria-valuenow', '50')
  })

  it('shows ellipsis for perspective count during download', () => {
    render(
      <ShellLoadAllProgressBar
        progress={progress({
          phase: 'download',
          perspective: 0,
          perspective_total: 0,
          turn: 0,
          turn_total: 0,
          message: 'Downloading loadall archive',
        })}
      />
    )
    expect(screen.getByText('…')).toBeInTheDocument()
    expect(screen.getByText(phaseMessage('Downloading loadall archive.'))).toBeInTheDocument()
  })

  it('cycles animated ellipsis on the phase message', () => {
    render(<ShellLoadAllProgressBar progress={progress()} />)
    expect(screen.getByText(phaseMessage('Perspective 2, turn 10.'))).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(400)
    })
    expect(screen.getByText(phaseMessage('Perspective 2, turn 10..'))).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(400)
    })
    expect(screen.getByText(phaseMessage('Perspective 2, turn 10...'))).toBeInTheDocument()
  })

  it('hides turns progress bar during final_turn phase', () => {
    render(
      <ShellLoadAllProgressBar
        progress={progress({
          phase: 'final_turn',
          perspective: 3,
          perspective_total: 11,
          turn: 1,
          turn_total: 1,
          message: 'Loading final turn for perspective 3',
        })}
      />
    )
    expect(screen.getByText('Perspectives')).toBeInTheDocument()
    expect(screen.getByText('3 / 11')).toBeInTheDocument()
    expect(screen.queryByText('Turns')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('progressbar', { name: 'Turn progress within perspective' })
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole('progressbar', { name: 'Perspective progress' })
    ).toBeInTheDocument()
  })
})
