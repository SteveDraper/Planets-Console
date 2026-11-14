import { describe, expect, it } from 'vitest'
import { toFetchRejectionError } from './bffSend'

describe('toFetchRejectionError', () => {
  it('includes endpoint and request path', () => {
    const e = toFetchRejectionError(
      new TypeError('Failed to fetch'),
      'GET /bff/games/1/info',
      '/bff/games/1/info'
    )
    expect(e.message).toContain('GET /bff/games/1/info')
    expect(e.message).toContain('request: /bff/games/1/info')
    expect(e.message).toContain('Failed to fetch')
    expect(e.message).toContain('No HTTP response')
  })

  it('appends Error.cause when present', () => {
    const inner = new Error('connection reset')
    const e = toFetchRejectionError(
      Object.assign(new TypeError('Failed to fetch'), { cause: inner }),
      'POST /bff/games/1/turns/ensure',
      '/bff/games/1/turns/ensure'
    )
    expect(e.message).toContain('cause:')
    expect(e.message).toContain('connection reset')
  })
})
