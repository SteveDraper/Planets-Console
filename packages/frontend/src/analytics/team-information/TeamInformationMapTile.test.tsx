import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { fetchLeagueTeams, type MapDataResponse } from '../../api/bff'
import { perspectiveRow } from '../../lib/perspectiveRowTestFixtures'
import { turnEnsureQueryKey } from '../../shell/shellContext'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../stellar-cartography/layers'
import { useSessionStore } from '../../stores/session'
import { useShellStore } from '../../stores/shell'
import { useTeamInformationHighlightStore } from '../../stores/teamInformationHighlight'
import {
  TEAM_INFORMATION_PREFERENCES_STORAGE_KEY,
  useTeamInformationPreferencesStore,
} from '../../stores/teamInformationPreferences'
import { defaultColorForPlayerId } from '../../lib/playerColor'
import { fetchTeamInformationMap } from './api'
import { TeamInformationMapTile } from './TeamInformationMapTile'

vi.mock('./api', () => ({
  fetchTeamInformationMap: vi.fn(),
}))

vi.mock('../../api/bff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/bff')>()
  return {
    ...actual,
    fetchLeagueTeams: vi.fn(),
  }
})

const sampleScope = {
  gameId: '628580',
  turn: 5,
  perspective: 1,
  username: 'alice',
}

const mapPayload: MapDataResponse = {
  analyticId: 'team-information',
  nodes: [],
  edges: [],
  regionOverlays: [],
  teamInformationTeams: [
    { leagueTeamId: 4, fillColor: '#38bdf8', fillPattern: 'forward', playerIds: [1, 2] },
  ],
  teamInformationPlayers: [{ playerId: 1 }, { playerId: 2 }],
}

function seedTurnRoster(client: QueryClient) {
  client.setQueryData(turnEnsureQueryKey(sampleScope, 'alice', 0), {
    ready: true,
    turnUsernamesByPlayerId: new Map([
      [1, 'alice'],
      [2, 'carol'],
    ]),
    turnRelations: [],
  })
}

function renderTile(ui: ReactNode, seed?: (client: QueryClient) => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  seed?.(client)
  return render(ui, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  })
}

describe('TeamInformationMapTile', () => {
  beforeEach(() => {
    localStorage.removeItem(TEAM_INFORMATION_PREFERENCES_STORAGE_KEY)
    useTeamInformationPreferencesStore.setState({
      ownedPlanetsOnly: false,
      hiddenLeagueTeamIds: [],
      byTeamByGameId: {},
      hiddenPlayerIdsByGameId: {},
    })
    useTeamInformationHighlightStore.setState({ hoveredTerritory: null })
    useSessionStore.setState({ name: 'alice', password: null, credentialsRevision: 0 })
    useShellStore.setState({
      gameInfoContext: {
        turn: 5,
        perspectives: [
          perspectiveRow(1, 'stale-alice', { playerId: 1 }),
          perspectiveRow(2, 'stale-bob', { playerId: 2 }),
        ],
        isGameFinished: true,
        sectorDisplayName: null,
        stellarCartographyGates: EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
        homeworldInactiveReason: null,
      },
    })
    vi.mocked(fetchTeamInformationMap).mockReset()
    vi.mocked(fetchTeamInformationMap).mockResolvedValue(mapPayload)
    vi.mocked(fetchLeagueTeams).mockReset()
    vi.mocked(fetchLeagueTeams).mockResolvedValue({
      teams: [{ id: 4, name: 'Blue Squadron' }],
    })
  })

  it('greys the tile in tabular mode', () => {
    const { container } = renderTile(
      <TeamInformationMapTile
        name="Territory"
        enabled
        supportsMode={false}
        depressed={false}
        onToggle={() => {}}
        analyticScope={sampleScope}
        turnDataReady
      />
    )
    expect(container.firstChild).toHaveClass('opacity-50')
    expect(screen.getByRole('checkbox', { name: 'Territory' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Expand Territory options' })).toBeDisabled()
    expect(screen.queryByRole('checkbox', { name: 'Owned planets only' })).not.toBeInTheDocument()
    expect(fetchTeamInformationMap).not.toHaveBeenCalled()
    expect(fetchLeagueTeams).not.toHaveBeenCalled()
  })

  it('shows player names by default and switches to league teams without a refetch', async () => {
    const user = userEvent.setup()
    renderTile(
      <TeamInformationMapTile
        name="Territory"
        enabled
        supportsMode
        depressed
        onToggle={() => {}}
        analyticScope={sampleScope}
        turnDataReady
      />,
      seedTurnRoster
    )
    await user.click(screen.getByRole('button', { name: 'Expand Territory options' }))
    expect(screen.getByRole('checkbox', { name: 'By team' })).not.toBeChecked()
    expect(await screen.findByText('alice')).toBeInTheDocument()
    expect(screen.getByText('carol')).toBeInTheDocument()
    expect(screen.queryByText('Blue Squadron')).not.toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Show alice territory' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Show carol territory' })).toBeChecked()
    const aliceSwatch = document.querySelector('[data-fill-pattern="solid"]')
    expect(aliceSwatch).toHaveStyle({ backgroundColor: defaultColorForPlayerId(1) })
    await user.hover(screen.getByText('alice'))
    expect(useTeamInformationHighlightStore.getState().hoveredTerritory).toEqual({
      partition: 'player',
      id: 1,
    })
    await user.unhover(screen.getByText('alice'))
    expect(useTeamInformationHighlightStore.getState().hoveredTerritory).toBeNull()
    await waitFor(() => {
      expect(fetchTeamInformationMap).toHaveBeenCalledTimes(1)
      expect(fetchLeagueTeams).toHaveBeenCalledTimes(1)
    })
    await user.click(screen.getByRole('checkbox', { name: 'By team' }))
    expect(useTeamInformationPreferencesStore.getState().byTeamByGameId).toEqual({
      '628580': true,
    })
    expect(await screen.findByText('Blue Squadron')).toBeInTheDocument()
    expect(screen.getByRole('listitem')).toHaveAttribute('title', 'alice, carol')
    expect(screen.queryByText('alice, carol')).not.toBeInTheDocument()
    expect(document.querySelector('[data-fill-pattern="forward"]')).not.toBeNull()
    await user.hover(screen.getByRole('listitem'))
    expect(useTeamInformationHighlightStore.getState().hoveredTerritory).toEqual({
      partition: 'team',
      id: 4,
    })
    await user.unhover(screen.getByRole('listitem'))
    expect(useTeamInformationHighlightStore.getState().hoveredTerritory).toBeNull()
    await user.click(screen.getByRole('checkbox', { name: 'Owned planets only' }))
    expect(useTeamInformationPreferencesStore.getState().ownedPlanetsOnly).toBe(true)
    expect(fetchTeamInformationMap).toHaveBeenCalledTimes(1)
    expect(fetchLeagueTeams).toHaveBeenCalledTimes(1)
  })

  it('starts player rows checked, persists an uncheck for this game, and still hovers', async () => {
    const user = userEvent.setup()
    renderTile(
      <TeamInformationMapTile
        name="Territory"
        enabled
        supportsMode
        depressed
        onToggle={() => {}}
        analyticScope={sampleScope}
        turnDataReady
      />,
      seedTurnRoster
    )
    await user.click(screen.getByRole('button', { name: 'Expand Territory options' }))
    const showAlice = await screen.findByRole('checkbox', { name: 'Show alice territory' })
    expect(showAlice).toBeChecked()
    const swatch = document.querySelector('[data-fill-pattern="solid"]')
    expect(swatch).toHaveStyle({ backgroundColor: defaultColorForPlayerId(1) })
    await user.click(showAlice)
    expect(showAlice).not.toBeChecked()
    expect(swatch).toHaveStyle({ backgroundColor: defaultColorForPlayerId(1) })
    expect(screen.getByRole('checkbox', { name: 'Show carol territory' })).toBeChecked()
    expect(useTeamInformationPreferencesStore.getState().hiddenPlayerIdsByGameId).toEqual({
      '628580': [1],
    })
    expect(useTeamInformationPreferencesStore.getState().hiddenLeagueTeamIds).toEqual([])
    expect(fetchTeamInformationMap).toHaveBeenCalledTimes(1)
    await user.hover(screen.getByText('alice'))
    expect(useTeamInformationHighlightStore.getState().hoveredTerritory).toEqual({
      partition: 'player',
      id: 1,
    })
    await user.unhover(screen.getByText('alice'))
    expect(useTeamInformationHighlightStore.getState().hoveredTerritory).toBeNull()
  })

  it('starts checked, persists an uncheck, and still hovers an unchecked row', async () => {
    const user = userEvent.setup()
    renderTile(
      <TeamInformationMapTile
        name="Territory"
        enabled
        supportsMode
        depressed
        onToggle={() => {}}
        analyticScope={sampleScope}
        turnDataReady
      />,
      seedTurnRoster
    )
    await user.click(screen.getByRole('button', { name: 'Expand Territory options' }))
    await user.click(screen.getByRole('checkbox', { name: 'By team' }))
    const showTerritory = await screen.findByRole('checkbox', {
      name: 'Show Blue Squadron territory',
    })
    expect(showTerritory).toBeChecked()
    await user.click(showTerritory)
    expect(showTerritory).not.toBeChecked()
    expect(useTeamInformationPreferencesStore.getState().hiddenLeagueTeamIds).toEqual([4])
    expect(fetchTeamInformationMap).toHaveBeenCalledTimes(1)
    await user.hover(screen.getByRole('listitem'))
    expect(useTeamInformationHighlightStore.getState().hoveredTerritory).toEqual({
      partition: 'team',
      id: 4,
    })
    await user.unhover(screen.getByRole('listitem'))
    expect(useTeamInformationHighlightStore.getState().hoveredTerritory).toBeNull()
  })

  it('shows the numeric id when the directory name is null and still hides usernames', async () => {
    const user = userEvent.setup()
    vi.mocked(fetchLeagueTeams).mockResolvedValue({
      teams: [{ id: 4, name: null }],
    })
    renderTile(
      <TeamInformationMapTile
        name="Territory"
        enabled
        supportsMode
        depressed
        onToggle={() => {}}
        analyticScope={sampleScope}
        turnDataReady
      />,
      seedTurnRoster
    )
    await user.click(screen.getByRole('button', { name: 'Expand Territory options' }))
    await user.click(screen.getByRole('checkbox', { name: 'By team' }))
    expect(await screen.findByText('4')).toBeInTheDocument()
    expect(screen.queryByText('alice, carol')).not.toBeInTheDocument()
    expect(screen.queryByText('alice')).not.toBeInTheDocument()
    expect(screen.queryByText('carol')).not.toBeInTheDocument()
  })

  it('shows the numeric player id when the roster name is missing', async () => {
    const user = userEvent.setup()
    useShellStore.setState({
      gameInfoContext: {
        turn: 5,
        perspectives: [],
        isGameFinished: true,
        sectorDisplayName: null,
        stellarCartographyGates: EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
        homeworldInactiveReason: null,
      },
    })
    renderTile(
      <TeamInformationMapTile
        name="Territory"
        enabled
        supportsMode
        depressed
        onToggle={() => {}}
        analyticScope={sampleScope}
        turnDataReady
      />
    )
    await user.click(screen.getByRole('button', { name: 'Expand Territory options' }))
    expect(await screen.findByText('1')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
  })

  it('clears a team hover while the player legend is shown, and clears on unmount', async () => {
    const user = userEvent.setup()
    useTeamInformationHighlightStore.setState({
      hoveredTerritory: { partition: 'team', id: 4 },
    })
    const { unmount } = renderTile(
      <TeamInformationMapTile
        name="Territory"
        enabled
        supportsMode
        depressed
        onToggle={() => {}}
        analyticScope={sampleScope}
        turnDataReady
      />,
      seedTurnRoster
    )
    await user.click(screen.getByRole('button', { name: 'Expand Territory options' }))
    expect(await screen.findByText('alice')).toBeInTheDocument()
    await waitFor(() => {
      expect(useTeamInformationHighlightStore.getState().hoveredTerritory).toBeNull()
    })
    await user.hover(screen.getByText('alice'))
    expect(useTeamInformationHighlightStore.getState().hoveredTerritory).toEqual({
      partition: 'player',
      id: 1,
    })
    unmount()
    expect(useTeamInformationHighlightStore.getState().hoveredTerritory).toBeNull()
  })

  it('does not write by team when no game is open', async () => {
    const user = userEvent.setup()
    renderTile(
      <TeamInformationMapTile
        name="Territory"
        enabled
        supportsMode
        depressed
        onToggle={() => {}}
        analyticScope={null}
        turnDataReady
      />
    )
    await user.click(screen.getByRole('button', { name: 'Expand Territory options' }))
    const byTeam = screen.getByRole('checkbox', { name: 'By team' })
    expect(byTeam).not.toBeChecked()
    await user.click(byTeam)
    expect(byTeam).not.toBeChecked()
    expect(useTeamInformationPreferencesStore.getState().byTeamByGameId).toEqual({})
  })
})
