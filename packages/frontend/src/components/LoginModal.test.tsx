import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LoginModal } from './LoginModal'
import {
  LAST_LOGIN_USERNAME_STORAGE_KEY,
  clearRememberedLoginUsername,
} from '../lib/rememberedLoginUsername'
import { useSessionStore } from '../stores/session'
import {
  dropCredentials,
  exchangeCredentials,
  probeCredentials,
} from '../api/credentialsClient'

vi.mock('../api/credentialsClient', () => ({
  exchangeCredentials: vi.fn().mockResolvedValue(undefined),
  probeCredentials: vi.fn().mockResolvedValue(true),
  dropCredentials: vi.fn().mockResolvedValue(undefined),
}))

describe('LoginModal', () => {
  beforeEach(() => {
    useSessionStore.getState().clearSession()
    localStorage.clear()
    vi.mocked(exchangeCredentials).mockClear().mockResolvedValue(undefined)
    vi.mocked(probeCredentials).mockClear().mockResolvedValue(true)
    vi.mocked(dropCredentials).mockClear().mockResolvedValue(undefined)
  })

  it('login exchange clears password from session', async () => {
    const user = userEvent.setup()
    const onIdentity = vi.fn()
    render(
      <LoginModal isOpen onClose={() => {}} onIdentityEstablished={onIdentity} />
    )
    await user.type(screen.getByLabelText(/^name$/i), 'Alice')
    await user.type(screen.getByLabelText(/^password$/i), 'secret')
    await user.click(screen.getByRole('button', { name: /log in/i }))
    await waitFor(() => {
      expect(exchangeCredentials).toHaveBeenCalledWith('Alice', 'secret')
    })
    expect(useSessionStore.getState().name).toBe('Alice')
    expect(useSessionStore.getState().password).toBeNull()
    expect(localStorage.getItem(LAST_LOGIN_USERNAME_STORAGE_KEY)).toBe('Alice')
    expect(onIdentity).toHaveBeenCalled()
  })

  it('name-only switch probes and adopts without exchange', async () => {
    const user = userEvent.setup()
    vi.mocked(probeCredentials).mockResolvedValue(true)
    render(<LoginModal isOpen onClose={() => {}} />)
    await user.type(screen.getByLabelText(/^name$/i), 'Bob')
    await user.click(screen.getByRole('button', { name: /log in/i }))
    await waitFor(() => {
      expect(probeCredentials).toHaveBeenCalledWith('Bob')
    })
    expect(exchangeCredentials).not.toHaveBeenCalled()
    expect(useSessionStore.getState().name).toBe('Bob')
    expect(useSessionStore.getState().password).toBeNull()
  })

  it('name-only switch shows error when probe fails', async () => {
    const user = userEvent.setup()
    vi.mocked(probeCredentials).mockResolvedValue(false)
    render(<LoginModal isOpen onClose={() => {}} />)
    await user.type(screen.getByLabelText(/^name$/i), 'Bob')
    await user.click(screen.getByRole('button', { name: /log in/i }))
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/password required/i)
    })
    expect(useSessionStore.getState().name).toBeNull()
  })

  it('log out clears remember-me and optionally drops key', async () => {
    const user = userEvent.setup()
    useSessionStore.getState().adoptLoginName('Alice')
    localStorage.setItem(LAST_LOGIN_USERNAME_STORAGE_KEY, 'Alice')
    render(<LoginModal isOpen onClose={() => {}} />)
    await user.click(screen.getByLabelText(/also delete stored account api key/i))
    await user.click(screen.getByRole('button', { name: /^log out$/i }))
    await waitFor(() => {
      expect(dropCredentials).toHaveBeenCalledWith('Alice')
    })
    expect(useSessionStore.getState().name).toBeNull()
    expect(localStorage.getItem(LAST_LOGIN_USERNAME_STORAGE_KEY)).toBeNull()
    clearRememberedLoginUsername()
  })
})
