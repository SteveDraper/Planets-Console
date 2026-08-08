import { describe, it, expect, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SettingsModal } from './SettingsModal'
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
    useShellStore.setState({ gameInfoContext: null })
  })

  it('shows empty state for per-player mode when no game is loaded', async () => {
    const user = userEvent.setup()
    render(<SettingsModal isOpen onClose={() => {}} />)
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
    render(<SettingsModal isOpen onClose={() => {}} />)
    await user.click(screen.getByText('Player Colors'))
    const colorInput = screen.getByLabelText(/color for alice/i) as HTMLInputElement
    expect(colorInput).toBeInTheDocument()
    fireEvent.change(colorInput, { target: { value: '#abcdef' } })
    expect(usePlayerColorsStore.getState().overrides['1']).toBe('#abcdef')
  })

  it('shows diplomacy knobs when mode is diplomacy-family', async () => {
    const user = userEvent.setup()
    render(<SettingsModal isOpen onClose={() => {}} />)
    await user.click(screen.getByText('Player Colors'))
    await user.selectOptions(screen.getByLabelText(/color by/i), 'diplomacy_family')
    expect(screen.getByLabelText(/minimum inbound status/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/diplomacy circle base color/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/others base color/i)).toBeInTheDocument()
    expect(usePlayerColorsStore.getState().mode).toBe('diplomacy_family')
  })
})
