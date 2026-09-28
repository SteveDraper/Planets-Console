import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { MapDataResponse } from '../../api/bff'
import { perspectiveRow } from '../../lib/perspectiveRowTestFixtures'
import { turnEnsureQueryKey } from '../../shell/shellContext'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../stellar-cartography/layers'
import { useSessionStore } from '../../stores/session'
import { useShellStore } from '../../stores/shell'
import {
  TEAM_INFORMATION_PREFERENCES_STORAGE_KEY,
  useTeamInformationPreferencesStore,
} from '../../stores/teamInformationPreferences'
import { fetchTeamInformationMap } from './api'
import { TeamInformationMapTile } from './TeamInformationMapTile'

vi.mock('./api', () => ({
  fetchTeamInformationMap: vi.fn(),
}))

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
    useTeamInformationPreferencesStore.setState({ ownedPlanetsOnly: false })
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
    for (const checkbox of screen.getAllByRole('checkbox')) {
      expect(checkbox).toBeDisabled()
    }
    expect(fetchTeamInformationMap).not.toHaveBeenCalled()
  })

  it('lists team id and turn-roster usernames, and toggling does not refetch', async () => {
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
      (client) => {
        client.setQueryData(
          turnEnsureQueryKey(sampleScope, 'alice', 0),
          {
            ready: true,
            turnUsernamesByPlayerId: new Map([
              [1, 'alice'],
              [2, 'carol'],
            ]),
            turnRelations: [],
          }
        )
      }
    )
    expect(await screen.findByText('alice, carol')).toBeInTheDocument()
    expect(screen.getByText('4')).toBeInTheDocument()
    expect(document.querySelector('[data-fill-pattern="forward"]')).not.toBeNull()
    await waitFor(() => {
      expect(fetchTeamInformationMap).toHaveBeenCalledTimes(1)
    })
    await user.click(screen.getByRole('checkbox', { name: 'Owned planets only' }))
    expect(useTeamInformationPreferencesStore.getState().ownedPlanetsOnly).toBe(true)
    expect(fetchTeamInformationMap).toHaveBeenCalledTimes(1)
  })
})
