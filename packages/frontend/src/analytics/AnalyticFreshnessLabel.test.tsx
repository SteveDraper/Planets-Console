import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AnalyticFreshnessLabel } from './AnalyticFreshnessLabel'

const PROVISIONAL_TITLE =
  'This is a saved answer from before a newer result for this player. It may change once that result is included. Backfill earlier turns updates turns you are not viewing. Otherwise a turn updates when you open it.'

describe('AnalyticFreshnessLabel', () => {
  it('shows turn load in slate with no title', () => {
    render(<AnalyticFreshnessLabel freshness="turn-load" />)

    const label = screen.getByText('Turn load')
    expect(label.className).toContain('text-xs')
    expect(label.className).toContain('text-slate-400')
    expect(label).not.toHaveAttribute('title')
  })

  it('shows Provisional in amber with a title', () => {
    render(<AnalyticFreshnessLabel freshness="subject-to-revision" />)

    const label = screen.getByText('Provisional')
    expect(label.className).toContain('text-amber-300')
    expect(label).toHaveAttribute('title', PROVISIONAL_TITLE)
  })

  it('renders nothing when freshness is none', () => {
    const { container } = render(<AnalyticFreshnessLabel freshness="none" />)

    expect(container).toBeEmptyDOMElement()
  })

  it('adds placement classes without dropping the tone', () => {
    render(
      <AnalyticFreshnessLabel freshness="turn-load" className="ml-2 font-normal" />
    )

    const label = screen.getByText('Turn load')
    expect(label.className).toContain('ml-2')
    expect(label.className).toContain('font-normal')
    expect(label.className).toContain('text-slate-400')
  })
})
