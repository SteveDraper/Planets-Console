import { afterEach, describe, expect, it, vi } from 'vitest'
import appVersion from '../assets/appVersion.json'
import { getAppVersionDisplayString } from './appVersion'

describe('getAppVersionDisplayString', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('returns version from appVersion.json when git env is unset', () => {
    vi.stubEnv('VITE_GIT_COMMIT_SHORT', '')
    expect(getAppVersionDisplayString()).toBe(appVersion.version)
  })

  it('appends short SHA in brackets when VITE_GIT_COMMIT_SHORT is set', () => {
    vi.stubEnv('VITE_GIT_COMMIT_SHORT', 'a1b2c3d')
    expect(getAppVersionDisplayString()).toBe(`${appVersion.version} (a1b2c3d)`)
  })

  it('trims whitespace from VITE_GIT_COMMIT_SHORT', () => {
    vi.stubEnv('VITE_GIT_COMMIT_SHORT', '  x9  ')
    expect(getAppVersionDisplayString()).toBe(`${appVersion.version} (x9)`)
  })
})
