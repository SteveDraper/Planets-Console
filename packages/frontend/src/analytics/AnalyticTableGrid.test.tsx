import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AnalyticTableGrid } from './AnalyticTableGrid'

describe('AnalyticTableGrid', () => {
  it('shows loading while the query is pending', () => {
    render(<AnalyticTableGrid isPending error={null} data={undefined} />)
    expect(screen.getByText('Loading…')).toBeInTheDocument()
  })

  it('shows the error detail when the query failed', () => {
    render(
      <AnalyticTableGrid isPending={false} error={new Error('backend down')} data={undefined} />
    )
    expect(screen.getByText(/Error loading data/)).toBeInTheDocument()
    expect(screen.getByText(/backend down/)).toBeInTheDocument()
  })

  it('renders nothing when there is no payload yet', () => {
    const { container } = render(
      <AnalyticTableGrid isPending={false} error={null} data={undefined} />
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the empty-grid message when columns or rows are missing', () => {
    render(
      <AnalyticTableGrid
        isPending={false}
        error={null}
        data={{ columns: undefined as unknown as string[], rows: [] }}
      />
    )
    expect(screen.getByText('This analytic has no tabular grid view.')).toBeInTheDocument()
  })

  it('renders column headers and row cells', () => {
    render(
      <AnalyticTableGrid
        isPending={false}
        error={null}
        data={{ columns: ['Player'], rows: [['Alice']] }}
      />
    )
    expect(screen.getByRole('columnheader', { name: 'Player' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'Alice' })).toBeInTheDocument()
  })
})
