import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { GameControl } from './GameControl'
import { useDisplayPreferencesStore } from '../stores/displayPreferences'

function renderGameControl(
  selectedGameId: string | null,
  onCommitGameSelection: (id: string) => void,
  options?: { isGameRefreshPending?: boolean; reportShellError?: (m: string) => void }
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <GameControl
        selectedGameId={selectedGameId}
        onCommitGameSelection={onCommitGameSelection}
        isGameRefreshPending={options?.isGameRefreshPending ?? false}
        reportShellError={options?.reportShellError ?? (() => {})}
      />
    </QueryClientProvider>
  )
}

describe('GameControl', () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.removeItem('planets-console-display-preferences')
    useDisplayPreferencesStore.setState({
      playerListLabelMode: 'player_names_only',
      sectorListLabelMode: 'sector_ids_only',
    })
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('shows None when no game is selected', () => {
    renderGameControl(null, () => {})
    expect(screen.getByRole('button', { name: /game:/i })).toHaveTextContent(/none/i)
  })

  it('shows selected game id on the trigger', () => {
    renderGameControl('628580', () => {})
    expect(screen.getByRole('button', { name: /game:/i })).toHaveTextContent('628580')
  })

  it('lists games from BFF when opened', async () => {
    const user = userEvent.setup()
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ games: [{ id: '111' }, { id: '222' }] }),
    }) as unknown as typeof fetch

    renderGameControl(null, () => {})
    await user.click(screen.getByRole('button', { name: /game:/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: '111' })).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: '222' })).toBeInTheDocument()
    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining('/bff/games'))
  })

  it('lists sector titles when settings ask for names and BFF provides sectorName', async () => {
    const user = userEvent.setup()
    useDisplayPreferencesStore.setState({ sectorListLabelMode: 'sector_names_only' })
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        games: [{ id: '111', sectorName: 'Alpha Sector' }],
      }),
    }) as unknown as typeof fetch

    renderGameControl(null, () => {})
    await user.click(screen.getByRole('button', { name: /game:/i }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Alpha Sector' })).toBeInTheDocument()
    })
  })

  it('calls onCommitGameSelection when a listed game is chosen', async () => {
    const user = userEvent.setup()
    const onCommit = vi.fn()
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ games: [{ id: '628580' }] }),
    }) as unknown as typeof fetch

    renderGameControl(null, onCommit)
    await user.click(screen.getByRole('button', { name: /game:/i }))
    await waitFor(() => expect(screen.getByRole('button', { name: '628580' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: '628580' }))
    expect(onCommit).toHaveBeenCalledWith('628580')
  })

  it('add game by id commits selection', async () => {
    const user = userEvent.setup()
    const onCommit = vi.fn()
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ games: [] }),
    }) as unknown as typeof fetch

    renderGameControl(null, onCommit)
    await user.click(screen.getByRole('button', { name: /game:/i }))
    await waitFor(() => expect(screen.getByLabelText(/new game id/i)).toBeInTheDocument())
    await user.type(screen.getByLabelText(/new game id/i), '999')
    await user.click(screen.getByRole('button', { name: /^add$/i }))
    expect(onCommit).toHaveBeenCalledWith('999')
  })
})
