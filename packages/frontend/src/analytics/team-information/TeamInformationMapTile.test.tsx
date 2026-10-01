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
    })
    useTeamInformationHighlightStore.setState({ hoveredLeagueTeamId: null })
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
        name="Team information"
        enabled
        supportsMode={false}
        depressed={false}
        onToggle={() => {}}
        analyticScope={sampleScope}
        turnDataReady
      />
    )
    expect(container.firstChild).toHaveClass('opacity-50')
    expect(screen.getByRole('checkbox', { name: 'Team information' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Expand Team information options' })).toBeDisabled()
    expect(screen.queryByRole('checkbox', { name: 'Owned planets only' })).not.toBeInTheDocument()
    expect(fetchTeamInformationMap).not.toHaveBeenCalled()
    expect(fetchLeagueTeams).not.toHaveBeenCalled()
  })

  it('shows the league team name, hides member usernames, and toggling does not refetch', async () => {
    const user = userEvent.setup()
    renderTile(
      <TeamInformationMapTile
        name="Team information"
        enabled
        supportsMode
        depressed
        onToggle={() => {}}
        analyticScope={sampleScope}
        turnDataReady
      />,
      seedTurnRoster
    )
    await user.click(screen.getByRole('button', { name: 'Expand Team information options' }))
    expect(await screen.findByText('Blue Squadron')).toBeInTheDocument()
    expect(screen.getByRole('listitem')).toHaveAttribute('title', 'alice, carol')
    expect(screen.queryByText('4')).not.toBeInTheDocument()
    expect(screen.queryByText('alice, carol')).not.toBeInTheDocument()
    expect(screen.queryByText('alice')).not.toBeInTheDocument()
    expect(screen.queryByText('carol')).not.toBeInTheDocument()
    expect(document.querySelector('[data-fill-pattern="forward"]')).not.toBeNull()
    await waitFor(() => {
      expect(fetchTeamInformationMap).toHaveBeenCalledTimes(1)
      expect(fetchLeagueTeams).toHaveBeenCalledTimes(1)
      expect(fetchLeagueTeams).toHaveBeenCalledWith('628580')
    })
    await user.hover(screen.getByRole('listitem'))
    expect(useTeamInformationHighlightStore.getState().hoveredLeagueTeamId).toBe(4)
    await user.unhover(screen.getByRole('listitem'))
    expect(useTeamInformationHighlightStore.getState().hoveredLeagueTeamId).toBeNull()
    await user.click(screen.getByRole('checkbox', { name: 'Owned planets only' }))
    expect(useTeamInformationPreferencesStore.getState().ownedPlanetsOnly).toBe(true)
    expect(fetchTeamInformationMap).toHaveBeenCalledTimes(1)
    expect(fetchLeagueTeams).toHaveBeenCalledTimes(1)
  })

  it('starts checked, persists an uncheck, and still hovers an unchecked row', async () => {
    const user = userEvent.setup()
    renderTile(
      <TeamInformationMapTile
        name="Team information"
        enabled
        supportsMode
        depressed
        onToggle={() => {}}
        analyticScope={sampleScope}
        turnDataReady
      />,
      seedTurnRoster
    )
    await user.click(screen.getByRole('button', { name: 'Expand Team information options' }))
    const showTerritory = await screen.findByRole('checkbox', {
      name: 'Show Blue Squadron territory',
    })
    expect(showTerritory).toBeChecked()
    await user.click(showTerritory)
    expect(showTerritory).not.toBeChecked()
    expect(useTeamInformationPreferencesStore.getState().hiddenLeagueTeamIds).toEqual([4])
    expect(fetchTeamInformationMap).toHaveBeenCalledTimes(1)
    await user.hover(screen.getByRole('listitem'))
    expect(useTeamInformationHighlightStore.getState().hoveredLeagueTeamId).toBe(4)
    await user.unhover(screen.getByRole('listitem'))
    expect(useTeamInformationHighlightStore.getState().hoveredLeagueTeamId).toBeNull()
  })

  it('shows the numeric id when the directory name is null and still hides usernames', async () => {
    const user = userEvent.setup()
    vi.mocked(fetchLeagueTeams).mockResolvedValue({
      teams: [{ id: 4, name: null }],
    })
    renderTile(
      <TeamInformationMapTile
        name="Team information"
        enabled
        supportsMode
        depressed
        onToggle={() => {}}
        analyticScope={sampleScope}
        turnDataReady
      />,
      seedTurnRoster
    )
    await user.click(screen.getByRole('button', { name: 'Expand Team information options' }))
    expect(await screen.findByText('4')).toBeInTheDocument()
    expect(screen.queryByText('alice, carol')).not.toBeInTheDocument()
    expect(screen.queryByText('alice')).not.toBeInTheDocument()
    expect(screen.queryByText('carol')).not.toBeInTheDocument()
  })
})
