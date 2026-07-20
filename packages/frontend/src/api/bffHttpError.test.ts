import { describe, expect, it } from 'vitest'
import {
  BffHttpError,
  isCredentialRequiredError,
  throwBffHttpError,
  withEndpointIfGeneric,
} from './bffHttpError'

describe('BffHttpError', () => {
  it('preserves HTTP status and detail', () => {
    const err = new BffHttpError(401, 'Login credentials are required.', 'POST /bff/ensure')
    expect(err).toBeInstanceOf(Error)
    expect(err.status).toBe(401)
    expect(err.detail).toBe('Login credentials are required.')
    expect(err.message).toBe('Login credentials are required.')
    expect(err.endpointLabel).toBe('POST /bff/ensure')
  })

  it('appends endpoint for generic server messages', () => {
    const err = new BffHttpError(500, 'Internal Server Error', 'POST /bff/ensure')
    expect(err.message).toBe('Internal Server Error (POST /bff/ensure)')
  })
})

describe('isCredentialRequiredError', () => {
  it('is true only for BffHttpError with status 401', () => {
    expect(isCredentialRequiredError(new BffHttpError(401, 'Login credentials are required.', 'x'))).toBe(
      true
    )
    expect(isCredentialRequiredError(new BffHttpError(403, 'Forbidden', 'x'))).toBe(false)
    expect(isCredentialRequiredError(new Error('Login credentials are required.'))).toBe(false)
    expect(isCredentialRequiredError('Login credentials are required.')).toBe(false)
  })
})

describe('throwBffHttpError', () => {
  it('throws BffHttpError', () => {
    expect(() => throwBffHttpError(401, 'denied', 'POST /bff/x')).toThrow(BffHttpError)
  })
})

describe('withEndpointIfGeneric (via bffHttpError)', () => {
  it('leaves specific messages alone', () => {
    expect(withEndpointIfGeneric('Login credentials are required.', 'POST /bff/x')).toBe(
      'Login credentials are required.'
    )
  })
})
