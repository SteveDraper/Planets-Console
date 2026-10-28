import { describe, it, expect, beforeEach, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { fetchBackfillEarlierTurns, putBackfillEarlierTurns } from '../api/bff'
import { SettingsModal } from './SettingsModal'

vi.mock('../api/bff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/bff')>()
  return {
    ...actual,
    fetchBackfillEarlierTurns: vi.fn(),
    putBackfillEarlierTurns: vi.fn(),
  }
})

function renderModal() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return render(
    <QueryClientProvider client={client}>
      <SettingsModal isOpen onClose={() => {}} />
    </QueryClientProvider>
  )
}
import { DiplomacyTier } from '../lib/diplomacyTier'
import { perspectiveRow } from '../lib/perspectiveRowTestFixtures'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../analytics/stellar-cartography/layers'
import {
  installPlayerColorsStorePort,
  resetPlayerColorsStoreState,
  usePlayerColorsStore,
} from '../stores/playerColors'
import { useShellStore } from '../stores/shell'
import { resetPlayerColorResolutionPort } from '../lib/playerColor'

describe('SettingsModal player colors', () => {
  beforeEach(() => {
    resetPlayerColorsStoreState({
      diplomacyThreshold: DiplomacyTier.SAFE_PASSAGE,
    })
    resetPlayerColorResolutionPort()
    installPlayerColorsStorePort()
    useShellStore.setState({ gameInfoContext: null, selectedGameId: null })
  })

  it('shows empty state for per-player mode when no game is loaded', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.click(screen.getByText('Player Colors'))
    expect(screen.getByText(/load a game to set player colors/i)).toBeInTheDocument()
  })

  it('lists roster and can set an override when a game is loaded', async () => {
    const user = userEvent.setup()
    useShellStore.setState({
      gameInfoContext: {
        turn: 5,
        isGameFinished: false,
        perspectives: [perspectiveRow(1, 'Alice'), perspectiveRow(2, 'Bob')],
        sectorDisplayName: null,
        stellarCartographyGates: EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
        homeworldInactiveReason: null,
      },
    })
    renderModal()
    await user.click(screen.getByText('Player Colors'))
    const colorInput = screen.getByLabelText(/color for alice/i) as HTMLInputElement
    expect(colorInput).toBeInTheDocument()
    fireEvent.change(colorInput, { target: { value: '#abcdef' } })
    expect(usePlayerColorsStore.getState().overrides['1']).toBe('#abcdef')
  })

  it('shows diplomacy knobs when mode is diplomacy-family', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.click(screen.getByText('Player Colors'))
    await user.selectOptions(screen.getByLabelText(/color by/i), 'diplomacy_family')
    expect(screen.getByLabelText(/minimum inbound status/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/diplomacy circle base color/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/others base color/i)).toBeInTheDocument()
    expect(usePlayerColorsStore.getState().mode).toBe('diplomacy_family')
  })

  it('ignores invalid mode and threshold select values', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.click(screen.getByText('Player Colors'))

    fireEvent.change(screen.getByLabelText(/color by/i), { target: { value: 'not_a_mode' } })
    expect(usePlayerColorsStore.getState().mode).toBe('per_player')

    await user.selectOptions(screen.getByLabelText(/color by/i), 'diplomacy_family')
    fireEvent.change(screen.getByLabelText(/minimum inbound status/i), {
      target: { value: '99' },
    })
    expect(usePlayerColorsStore.getState().diplomacyThreshold).toBe(DiplomacyTier.SAFE_PASSAGE)
  })
})

describe('SettingsModal backfill earlier turns', () => {
  beforeEach(() => {
    useShellStore.setState({
      selectedGameId: null,
      perspectiveOverrideOrdinal: null,
    })
    vi.mocked(fetchBackfillEarlierTurns).mockReset()
    vi.mocked(putBackfillEarlierTurns).mockReset()
  })

  it('keeps the checkbox off and disabled until a game is selected', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.click(screen.getByText('Inference', { selector: 'summary' }))
    expect(screen.getByRole('checkbox', { name: 'Backfill earlier turns' })).toBeDisabled()
    expect(screen.getByText(/select a game to change this setting/i)).toBeInTheDocument()
    expect(
      screen.getByText(/this primarily impacts fleet ledgers and scoreboard inference/i)
    ).toBeInTheDocument()
    expect(putBackfillEarlierTurns).not.toHaveBeenCalled()
  })

  it('saves one game-wide value from the checkbox', async () => {
    const user = userEvent.setup()
    useShellStore.setState({
      selectedGameId: '628580',
      perspectiveOverrideOrdinal: 2,
    })
    vi.mocked(fetchBackfillEarlierTurns).mockResolvedValue({ backfillEarlierTurns: false })
    vi.mocked(putBackfillEarlierTurns).mockImplementation(async (_gameId, enabled) => ({
      backfillEarlierTurns: enabled,
    }))

    renderModal()
    await user.click(screen.getByText('Inference', { selector: 'summary' }))
    const checkbox = await screen.findByRole('checkbox', { name: 'Backfill earlier turns' })
    await waitFor(() => expect(checkbox).toBeEnabled())
    expect(checkbox).not.toBeChecked()
    expect(fetchBackfillEarlierTurns).toHaveBeenCalledWith('628580')

    await user.click(checkbox)
    expect(putBackfillEarlierTurns).toHaveBeenCalledWith('628580', true)
    expect(await screen.findByRole('checkbox', { name: 'Backfill earlier turns' })).toBeChecked()
  })
})
