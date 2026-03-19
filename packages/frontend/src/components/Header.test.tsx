import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Header } from './Header'
import { useSessionStore } from '../stores/session'

const headerQueryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
})

function renderHeader() {
  return render(
    <QueryClientProvider client={headerQueryClient}>
      <Header
        viewMode="tabular"
        onViewModeChange={() => {}}
        mapZoom={1}
        onMapZoomSliderChange={() => {}}
        selectedGameId={null}
        onSelectGameId={() => {}}
      />
    </QueryClientProvider>
  )
}

describe('Header', () => {
  beforeEach(() => {
    useSessionStore.getState().clearSession()
    localStorage.clear()
    sessionStorage.clear()
    headerQueryClient.clear()
  })

  it('shows change-login button and placeholder when not logged in', () => {
    renderHeader()
    expect(screen.getByRole('button', { name: /change login/i })).toBeInTheDocument()
    const loginSection = screen.getByTitle('Login identity')
    expect(loginSection).toHaveTextContent('Login:')
    expect(loginSection).toHaveTextContent('—')
  })

  it('opens login modal when change-login button is clicked', async () => {
    const user = userEvent.setup()
    renderHeader()
    await user.click(screen.getByRole('button', { name: /change login/i }))
    expect(screen.getByRole('dialog', { name: /log in to planets\.nu/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/name/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument()
  })

  it('shows login name after submitting credentials', async () => {
    const user = userEvent.setup()
    renderHeader()
    await user.click(screen.getByRole('button', { name: /change login/i }))
    await user.type(screen.getByLabelText(/name/i), 'TestPlayer')
    await user.type(screen.getByLabelText(/password/i), 'secret')
    await user.click(screen.getByRole('button', { name: /log in/i }))
    expect(screen.getByText('TestPlayer')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('restores focus to change-login button when modal closes (Cancel)', async () => {
    const user = userEvent.setup()
    renderHeader()
    const changeLoginButton = screen.getByRole('button', { name: /change login/i })
    await user.click(changeLoginButton)
    expect(screen.getByRole('dialog', { name: /log in to planets\.nu/i })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /cancel/i }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await waitFor(() => expect(changeLoginButton).toHaveFocus())
  })

  it('change-login button is always present and opens modal when logged in', async () => {
    const user = userEvent.setup()
    useSessionStore.getState().setCredentials('Someone', 'pass')
    renderHeader()
    expect(screen.getByText('Someone')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /change login/i }))
    expect(screen.getByRole('dialog', { name: /log in to planets\.nu/i })).toBeInTheDocument()
  })

  it('does not persist password to localStorage or sessionStorage', async () => {
    const user = userEvent.setup()
    renderHeader()
    await user.click(screen.getByRole('button', { name: /change login/i }))
    await user.type(screen.getByLabelText(/name/i), 'User')
    await user.type(screen.getByLabelText(/password/i), 'sensitive-password')
    await user.click(screen.getByRole('button', { name: /log in/i }))
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
    const localKeys = Object.keys(localStorage)
    const sessionKeys = Object.keys(sessionStorage)
    const localStr = localKeys.length ? localKeys.map((k) => localStorage.getItem(k)).join('') : ''
    const sessionStr = sessionKeys.length
      ? sessionKeys.map((k) => sessionStorage.getItem(k)).join('')
      : ''
    expect(localStr).not.toContain('sensitive-password')
    expect(sessionStr).not.toContain('sensitive-password')
  })
})
