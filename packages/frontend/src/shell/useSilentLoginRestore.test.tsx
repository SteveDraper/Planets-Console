import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { LAST_LOGIN_USERNAME_STORAGE_KEY } from '../components/LoginModal'
import { useSilentLoginRestore } from './useSilentLoginRestore'
import { useSessionStore } from '../stores/session'
import { probeCredentials } from '../api/bff'

vi.mock('../api/bff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/bff')>()
  return {
    ...actual,
    probeCredentials: vi.fn(),
  }
})

describe('useSilentLoginRestore', () => {
  beforeEach(() => {
    useSessionStore.getState().clearSession()
    localStorage.clear()
    vi.mocked(probeCredentials).mockReset()
  })

  it('skips when no remembered username', async () => {
    const { result } = renderHook(() => useSilentLoginRestore(true))
    await waitFor(() => expect(result.current.status).toBe('skipped'))
    expect(probeCredentials).not.toHaveBeenCalled()
    expect(result.current.shouldOpenLoginModal).toBe(false)
  })

  it('restores session name when probe succeeds', async () => {
    localStorage.setItem(LAST_LOGIN_USERNAME_STORAGE_KEY, 'Alice')
    vi.mocked(probeCredentials).mockResolvedValue(true)
    const { result } = renderHook(() => useSilentLoginRestore(true))
    await waitFor(() => expect(result.current.status).toBe('restored'))
    expect(useSessionStore.getState().name).toBe('Alice')
    expect(useSessionStore.getState().password).toBeNull()
    expect(result.current.shouldOpenLoginModal).toBe(false)
  })

  it('opens login modal when probe fails', async () => {
    localStorage.setItem(LAST_LOGIN_USERNAME_STORAGE_KEY, 'Alice')
    vi.mocked(probeCredentials).mockResolvedValue(false)
    const { result } = renderHook(() => useSilentLoginRestore(true))
    await waitFor(() => expect(result.current.status).toBe('failed'))
    expect(useSessionStore.getState().name).toBeNull()
    expect(result.current.shouldOpenLoginModal).toBe(true)
  })
})
