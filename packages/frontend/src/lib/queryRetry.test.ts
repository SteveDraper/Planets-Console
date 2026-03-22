import { describe, it, expect } from 'vitest'
import { parseHttpStatusFromErrorMessage, shouldRetryTanStackQuery } from './queryRetry'

describe('parseHttpStatusFromErrorMessage', () => {
  it('reads leading status code', () => {
    expect(parseHttpStatusFromErrorMessage('502 (POST /bff/x)')).toBe(502)
    expect(parseHttpStatusFromErrorMessage('503 Service Unavailable (GET /bff/y)')).toBe(503)
  })

  it('maps common status phrases', () => {
    expect(parseHttpStatusFromErrorMessage('Bad Gateway (POST /bff/x)')).toBe(502)
    expect(parseHttpStatusFromErrorMessage('Gateway Timeout')).toBe(504)
    expect(parseHttpStatusFromErrorMessage('Service Unavailable')).toBe(503)
  })
})

describe('shouldRetryTanStackQuery', () => {
  it('does not retry 4xx', () => {
    expect(shouldRetryTanStackQuery(0, new Error('404 (GET /bff/x)'))).toBe(false)
    expect(shouldRetryTanStackQuery(0, new Error('422 Unprocessable'))).toBe(false)
  })

  it('does not retry 502 or 500', () => {
    expect(shouldRetryTanStackQuery(0, new Error('502 (POST /bff/x)'))).toBe(false)
    expect(shouldRetryTanStackQuery(0, new Error('Bad Gateway (POST /bff/x)'))).toBe(false)
    expect(shouldRetryTanStackQuery(0, new Error('500 (GET /bff/x)'))).toBe(false)
    expect(shouldRetryTanStackQuery(0, new Error('Internal Server Error'))).toBe(false)
  })

  it('retries 503, 504, and 408 until cap', () => {
    expect(shouldRetryTanStackQuery(0, new Error('503 (GET /bff/x)'))).toBe(true)
    expect(shouldRetryTanStackQuery(2, new Error('504 Gateway Timeout'))).toBe(true)
    expect(shouldRetryTanStackQuery(0, new Error('408 Request Timeout'))).toBe(true)
    expect(shouldRetryTanStackQuery(3, new Error('503'))).toBe(false)
  })

  it('retries likely network failures until cap', () => {
    expect(shouldRetryTanStackQuery(0, new TypeError('Failed to fetch'))).toBe(true)
    expect(shouldRetryTanStackQuery(0, new Error('Failed to fetch'))).toBe(true)
    expect(shouldRetryTanStackQuery(3, new TypeError('Failed to fetch'))).toBe(false)
  })

  it('does not retry unknown errors', () => {
    expect(shouldRetryTanStackQuery(0, new Error('Something broke'))).toBe(false)
  })
})
