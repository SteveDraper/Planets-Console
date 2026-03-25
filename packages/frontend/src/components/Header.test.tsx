import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useState } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Header } from './Header'
import { LAST_LOGIN_USERNAME_STORAGE_KEY } from './LoginModal'
import { useDisplayPreferencesStore } from '../stores/displayPreferences'
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
        onCommitGameSelection={() => {}}
        isGameRefreshPending={false}
        reportShellError={() => {}}
        shellTurnMax={null}
        shellTurnValue={null}
        onShellTurnChange={() => {}}
        shellViewpoints={[]}
        shellSelectedViewpointName={null}
        onShellViewpointChange={() => {}}
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
    useDisplayPreferencesStore.setState({
      playerListLabelMode: 'player_names_only',
      sectorListLabelMode: 'sector_ids_only',
    })
  })

  it('shows change-login button and placeholder when not logged in', () => {
    renderHeader()
    expect(screen.getByRole('button', { name: /change login/i })).toBeInTheDocument()
    const loginSection = screen.getByTitle('Login identity')
    expect(loginSection).toHaveTextContent('Login:')
    expect(loginSection).toHaveTextContent('—')
  })

  it('shows turn placeholder when max turn is unknown', () => {
    renderHeader()
    const turnRegion = screen.getByTitle('Turn (game year)')
    expect(turnRegion).toHaveTextContent('Turn')
    expect(turnRegion).toHaveTextContent('—')
    expect(screen.queryByLabelText(/turn number/i)).not.toBeInTheDocument()
  })

  it('shows viewpoint placeholder when no perspectives', () => {
    renderHeader()
    const viewpointRegion = screen.getByTitle('Viewpoint')
    expect(viewpointRegion).toHaveTextContent('Viewpoint')
    expect(viewpointRegion).toHaveTextContent('—')
    expect(screen.queryByLabelText(/^viewpoint$/i)).not.toBeInTheDocument()
  })

  it('opens settings from the header menu', async () => {
    const user = userEvent.setup()
    renderHeader()
    await user.click(screen.getByRole('button', { name: /open menu/i }))
    await user.click(screen.getByRole('menuitem', { name: /^settings$/i }))
    expect(screen.getByRole('dialog', { name: /^settings$/i })).toBeInTheDocument()
  })

  it('renders viewpoint as a dropdown and reports changes', async () => {
    const user = userEvent.setup()
    const onViewpoint = vi.fn()
    render(
      <QueryClientProvider client={headerQueryClient}>
        <Header
          viewMode="tabular"
          onViewModeChange={() => {}}
          mapZoom={1}
          onMapZoomSliderChange={() => {}}
          selectedGameId={null}
          onCommitGameSelection={() => {}}
          isGameRefreshPending={false}
          reportShellError={() => {}}
          shellTurnMax={null}
          shellTurnValue={null}
          onShellTurnChange={() => {}}
          shellViewpoints={[
            { name: 'Alpha', raceName: null, disabled: false },
            { name: 'Beta', raceName: null, disabled: false },
          ]}
          shellSelectedViewpointName="Alpha"
          onShellViewpointChange={onViewpoint}
        />
      </QueryClientProvider>
    )
    const select = screen.getByLabelText(/^viewpoint$/i)
    expect(select).toHaveValue('Alpha')
    await user.selectOptions(select, 'Beta')
    expect(onViewpoint).toHaveBeenCalledWith('Beta')
  })

  it('marks disabled viewpoint options and keeps only the active slot selectable', () => {
    const onViewpoint = vi.fn()
    render(
      <QueryClientProvider client={headerQueryClient}>
        <Header
          viewMode="tabular"
          onViewModeChange={() => {}}
          mapZoom={1}
          onMapZoomSliderChange={() => {}}
          selectedGameId={null}
          onCommitGameSelection={() => {}}
          isGameRefreshPending={false}
          reportShellError={() => {}}
          shellTurnMax={null}
          shellTurnValue={null}
          onShellTurnChange={() => {}}
          shellViewpoints={[
            { name: 'Alpha', raceName: null, disabled: false },
            { name: 'Beta', raceName: null, disabled: true },
          ]}
          shellSelectedViewpointName="Alpha"
          onShellViewpointChange={onViewpoint}
        />
      </QueryClientProvider>
    )
    expect(screen.getByRole('option', { name: 'Alpha' })).not.toBeDisabled()
    expect(screen.getByRole('option', { name: 'Beta' })).toBeDisabled()
  })

  it('turn stepper clamps to 1 and max turn', async () => {
    const user = userEvent.setup()
    function Wrapper() {
      const [t, setT] = useState(2)
      return (
        <QueryClientProvider client={headerQueryClient}>
          <Header
            viewMode="tabular"
            onViewModeChange={() => {}}
            mapZoom={1}
            onMapZoomSliderChange={() => {}}
            selectedGameId={null}
            onCommitGameSelection={() => {}}
            isGameRefreshPending={false}
            reportShellError={() => {}}
            shellTurnMax={3}
            shellTurnValue={t}
            onShellTurnChange={setT}
            shellViewpoints={[]}
            shellSelectedViewpointName={null}
            onShellViewpointChange={() => {}}
          />
        </QueryClientProvider>
      )
    }
    render(<Wrapper />)
    const input = screen.getByLabelText(/turn number/i)
    expect(input).toHaveValue(2)
    const dec = screen.getByRole('button', { name: /decrease turn/i })
    const inc = screen.getByRole('button', { name: /increase turn/i })
    await user.click(dec)
    expect(input).toHaveValue(1)
    expect(dec).toBeDisabled()
    await user.click(inc)
    expect(input).toHaveValue(2)
    await user.click(inc)
    expect(input).toHaveValue(3)
    expect(inc).toBeDisabled()
  })

  it('prefills name from localStorage when opening login modal', async () => {
    const user = userEvent.setup()
    localStorage.setItem(LAST_LOGIN_USERNAME_STORAGE_KEY, 'PrefilledUser')
    renderHeader()
    await user.click(screen.getByRole('button', { name: /change login/i }))
    expect(screen.getByLabelText(/^name$/i)).toHaveValue('PrefilledUser')
    expect(screen.getByLabelText(/^password$/i)).toHaveValue('')
    expect(screen.getByLabelText(/^password$/i)).toHaveFocus()
  })

  it('focuses name field when no saved username in localStorage', async () => {
    const user = userEvent.setup()
    renderHeader()
    await user.click(screen.getByRole('button', { name: /change login/i }))
    expect(screen.getByLabelText(/^name$/i)).toHaveFocus()
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

  it('persists last username in localStorage but not password', async () => {
    const user = userEvent.setup()
    renderHeader()
    await user.click(screen.getByRole('button', { name: /change login/i }))
    await user.type(screen.getByLabelText(/^name$/i), 'User')
    await user.type(screen.getByLabelText(/^password$/i), 'sensitive-password')
    await user.click(screen.getByRole('button', { name: /log in/i }))
    expect(localStorage.getItem(LAST_LOGIN_USERNAME_STORAGE_KEY)).toBe('User')
    expect(sessionStorage.length).toBe(0)
    const sessionKeys = Object.keys(sessionStorage)
    const sessionStr = sessionKeys.length
      ? sessionKeys.map((k) => sessionStorage.getItem(k)).join('')
      : ''
    expect(sessionStr).not.toContain('sensitive-password')
    const localStr = Object.keys(localStorage)
      .map((k) => localStorage.getItem(k) ?? '')
      .join('')
    expect(localStr).not.toContain('sensitive-password')
  })
})
