import { describe, it, expect } from 'vitest'
import { isGenericServerErrorMessage, withEndpointIfGeneric } from './bff'

describe('withEndpointIfGeneric', () => {
  it('appends endpoint for Internal Server Error', () => {
    expect(
      withEndpointIfGeneric('Internal Server Error', 'POST /bff/games/1/info')
    ).toBe('Internal Server Error (POST /bff/games/1/info)')
  })

  it('does not append for specific API messages', () => {
    expect(
      withEndpointIfGeneric('Login credentials are required.', 'POST /bff/games/1/info')
    ).toBe('Login credentials are required.')
  })

  it('appends for bare 500 status message', () => {
    expect(withEndpointIfGeneric('500', 'GET /bff/games')).toBe('500 (GET /bff/games)')
  })

  it('does not append for 404', () => {
    expect(withEndpointIfGeneric('404', 'GET /bff/games')).toBe('404')
  })

  it('does not duplicate endpoint if already present', () => {
    expect(
      withEndpointIfGeneric('500 (GET /bff/games)', 'GET /bff/games')
    ).toBe('500 (GET /bff/games)')
  })
})

describe('isGenericServerErrorMessage', () => {
  it('treats empty as generic', () => {
    expect(isGenericServerErrorMessage('')).toBe(true)
  })
})
