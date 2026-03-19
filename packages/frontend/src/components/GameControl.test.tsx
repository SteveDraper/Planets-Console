import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { GameControl } from './GameControl'

function renderGameControl(
  selectedGameId: string | null,
  onSelectGameId: (id: string | null) => void
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <GameControl selectedGameId={selectedGameId} onSelectGameId={onSelectGameId} />
    </QueryClientProvider>
  )
}

describe('GameControl', () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    vi.restoreAllMocks()
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
      expect(screen.getByRole('option', { name: '111' })).toBeInTheDocument()
    })
    expect(screen.getByRole('option', { name: '222' })).toBeInTheDocument()
    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining('/bff/games'))
  })

  it('calls onSelectGameId when a listed game is chosen', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ games: [{ id: '628580' }] }),
    }) as unknown as typeof fetch

    renderGameControl(null, onSelect)
    await user.click(screen.getByRole('button', { name: /game:/i }))
    await waitFor(() => expect(screen.getByRole('option', { name: '628580' })).toBeInTheDocument())
    await user.click(screen.getByRole('option', { name: '628580' }))
    expect(onSelect).toHaveBeenCalledWith('628580')
  })

  it('add game by id updates selection', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ games: [] }),
    }) as unknown as typeof fetch

    renderGameControl(null, onSelect)
    await user.click(screen.getByRole('button', { name: /game:/i }))
    await waitFor(() => expect(screen.getByLabelText(/new game id/i)).toBeInTheDocument())
    await user.type(screen.getByLabelText(/new game id/i), '999')
    await user.click(screen.getByRole('button', { name: /^add$/i }))
    expect(onSelect).toHaveBeenCalledWith('999')
  })
})
