import { describe, it, expect } from 'vitest'
import { BffHttpError } from '../api/bffHttpError'
import {
  errorDetailFromUnknown,
  httpStatusFromError,
  parseHttpStatusFromErrorMessage,
  shouldRetryTanStackQuery,
} from './queryRetry'

describe('errorDetailFromUnknown', () => {
  it('formats Error, other values, and nullish with fallback', () => {
    expect(errorDetailFromUnknown(new Error('boom'))).toBe('boom')
    expect(errorDetailFromUnknown('plain')).toBe('plain')
    expect(errorDetailFromUnknown(null, 'fallback')).toBe('fallback')
  })
})

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

describe('httpStatusFromError', () => {
  it('prefers the typed status over the message', () => {
    const err = new BffHttpError(503, 'Homeworld layout prior is warming up', 'GET /bff/x')
    expect(httpStatusFromError(err)).toBe(503)
  })

  it('falls back to message parsing for untyped errors', () => {
    expect(httpStatusFromError(new Error('504 Gateway Timeout'))).toBe(504)
    expect(httpStatusFromError('nothing numeric')).toBeNull()
  })
})

describe('shouldRetryTanStackQuery', () => {
  it('retries transient BffHttpError statuses regardless of detail wording', () => {
    for (const status of [408, 503, 504]) {
      const err = new BffHttpError(status, 'Layout prior evidence is not ready', 'GET /bff/x')
      expect(shouldRetryTanStackQuery(0, err)).toBe(true)
    }
  })

  it('does not retry non-transient BffHttpError statuses', () => {
    expect(
      shouldRetryTanStackQuery(0, new BffHttpError(401, 'Login credentials are required.', 'GET /bff/x'))
    ).toBe(false)
    expect(shouldRetryTanStackQuery(0, new BffHttpError(404, 'Turn not found', 'GET /bff/x'))).toBe(
      false
    )
    expect(
      shouldRetryTanStackQuery(0, new BffHttpError(502, 'Forbidden perspective', 'GET /bff/x'))
    ).toBe(false)
    expect(shouldRetryTanStackQuery(0, new BffHttpError(500, 'Solver crashed', 'GET /bff/x'))).toBe(
      false
    )
  })

  it('stops retrying BffHttpError at the failure cap', () => {
    const err = new BffHttpError(503, 'Service Unavailable', 'GET /bff/x')
    expect(shouldRetryTanStackQuery(2, err)).toBe(true)
    expect(shouldRetryTanStackQuery(3, err)).toBe(false)
  })

  it('does not treat a typed 4xx with network-sounding detail as a network failure', () => {
    const err = new BffHttpError(400, 'Failed to fetch upstream turn data', 'GET /bff/x')
    expect(shouldRetryTanStackQuery(0, err)).toBe(false)
  })

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
