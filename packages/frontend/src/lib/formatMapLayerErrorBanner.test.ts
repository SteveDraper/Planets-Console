import { describe, expect, it } from 'vitest'
import { BffHttpError } from '../api/bffHttpError'
import { formatMapLayerErrorBanner } from './formatMapLayerErrorBanner'

describe('formatMapLayerErrorBanner', () => {
  it('names the analytic and includes the failure detail', () => {
    const text = formatMapLayerErrorBanner([
      {
        analyticId: 'homeworld-locator',
        analyticName: 'Homeworld locator',
        error: new BffHttpError(
          422,
          'homeworld locator cannot refine turn 60: turn 59 is not stored (evidence chain requires contiguous turns)',
          'GET /bff/analytics/homeworld-locator/map'
        ),
      },
    ])
    expect(text).toMatch(/Homeworld locator/i)
    expect(text).toMatch(/turn 59 is not stored/i)
    expect(text).not.toMatch(/^422$/)
  })

  it('prefixes catalog name when detail does not already name it', () => {
    expect(
      formatMapLayerErrorBanner([
        {
          analyticId: 'connections',
          analyticName: 'Connections',
          error: new Error('warpSpeed must be between 1 and 9.'),
        },
      ])
    ).toBe('Connections: warpSpeed must be between 1 and 9.')
  })

  it('joins multiple layer failures', () => {
    const text = formatMapLayerErrorBanner([
      {
        analyticId: 'homeworld-locator',
        analyticName: 'Homeworld locator',
        error: new Error('turn 59 is not stored'),
      },
      {
        analyticId: 'fleet',
        analyticName: 'Fleet',
        error: new Error('gap fill timed out'),
      },
    ])
    expect(text).toContain('Homeworld locator: turn 59 is not stored')
    expect(text).toContain('Fleet: gap fill timed out')
  })
})
