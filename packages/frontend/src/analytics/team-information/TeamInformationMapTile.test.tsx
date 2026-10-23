import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
import {
  closeTerritoryMovieWindow,
  prepareTerritoryMovie,
  reserveTerritoryMovieWindow,
  showTerritoryMovieDocument,
} from './prepareTerritoryMovie'
import { TeamInformationMapTile } from './TeamInformationMapTile'

vi.mock('./prepareTerritoryMovie', () => ({
  prepareTerritoryMovie: vi.fn(),
  reserveTerritoryMovieWindow: vi.fn(() => ({ close: vi.fn(), closed: false })),
  showTerritoryMovieDocument: vi.fn(),
  closeTerritoryMovieWindow: vi.fn(),
}))

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
    vi.mocked(prepareTerritoryMovie).mockReset()
    vi.mocked(reserveTerritoryMovieWindow).mockReset()
    vi.mocked(reserveTerritoryMovieWindow).mockReturnValue({ close: vi.fn(), closed: false } as unknown as Window)
    vi.mocked(showTerritoryMovieDocument).mockReset()
    vi.mocked(closeTerritoryMovieWindow).mockReset()
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
        reportShellError={() => {}}
      />
    )
    expect(container.firstChild).toHaveClass('opacity-50')
    expect(screen.getByRole('checkbox', { name: 'Territory' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Expand Territory options' })).toBeDisabled()
    expect(screen.queryByRole('checkbox', { name: 'Owned planets only' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Generate movie' })).not.toBeInTheDocument()
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
        reportShellError={() => {}}
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
    expect(screen.getByTitle('alice, carol')).toBeInTheDocument()
    expect(screen.getByRole('listitem')).not.toHaveAttribute('title')
    expect(screen.queryByText('alice, carol')).not.toBeInTheDocument()
    expect(document.querySelector('[data-fill-pattern="forward"]')).not.toBeNull()
    await user.hover(screen.getByText('Blue Squadron'))
    expect(useTeamInformationHighlightStore.getState().hoveredTerritory).toEqual({
      partition: 'team',
      id: 4,
    })
    await user.unhover(screen.getByText('Blue Squadron'))
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
        reportShellError={() => {}}
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
        reportShellError={() => {}}
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
    await user.hover(screen.getByText('Blue Squadron'))
    expect(useTeamInformationHighlightStore.getState().hoveredTerritory).toEqual({
      partition: 'team',
      id: 4,
    })
    await user.unhover(screen.getByText('Blue Squadron'))
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
        reportShellError={() => {}}
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
        reportShellError={() => {}}
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
        reportShellError={() => {}}
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

  it('hovers the color chip and the name, and ignores the checkbox', async () => {
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
        reportShellError={() => {}}
      />,
      seedTurnRoster
    )
    await user.click(screen.getByRole('button', { name: 'Expand Territory options' }))
    const swatch = await waitFor(() => {
      const chip = document.querySelector('[data-fill-pattern="solid"]')
      expect(chip).not.toBeNull()
      return chip as Element
    })
    await user.hover(swatch)
    expect(useTeamInformationHighlightStore.getState().hoveredTerritory).toEqual({
      partition: 'player',
      id: 1,
    })
    await user.unhover(swatch)
    expect(useTeamInformationHighlightStore.getState().hoveredTerritory).toBeNull()
    await user.hover(screen.getByRole('checkbox', { name: 'Show alice territory' }))
    expect(useTeamInformationHighlightStore.getState().hoveredTerritory).toBeNull()
  })

  it('clears the highlight while the analytics bar scrolls, then restores the name under the pointer', async () => {
    renderTile(
      <div style={{ height: 40, overflowY: 'auto' }}>
        <TeamInformationMapTile
          name="Territory"
          enabled
          supportsMode
          depressed
          onToggle={() => {}}
          analyticScope={sampleScope}
          turnDataReady
          reportShellError={() => {}}
        />
      </div>,
      seedTurnRoster
    )
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Expand Territory options' }))
    expect(await screen.findByText('alice')).toBeInTheDocument()
    let ancestor: HTMLElement | null = screen.getByRole('list', { name: 'Players' })
    while (ancestor != null && getComputedStyle(ancestor).overflowY !== 'auto') {
      ancestor = ancestor.parentElement
    }
    expect(ancestor).not.toBeNull()
    fireEvent.pointerMove(document, { clientX: 12, clientY: 12 })
    const originalElementFromPoint = document.elementFromPoint?.bind(document)
    document.elementFromPoint = () => screen.getByText('alice')
    try {
      await user.hover(screen.getByText('alice'))
      expect(useTeamInformationHighlightStore.getState().hoveredTerritory).toEqual({
        partition: 'player',
        id: 1,
      })
      fireEvent.scroll(ancestor as HTMLElement)
      expect(useTeamInformationHighlightStore.getState().hoveredTerritory).toBeNull()
      fireEvent.mouseEnter(screen.getByText('alice').parentElement as HTMLElement)
      expect(useTeamInformationHighlightStore.getState().hoveredTerritory).toBeNull()
      await waitFor(() => {
        expect(useTeamInformationHighlightStore.getState().hoveredTerritory).toEqual({
          partition: 'player',
          id: 1,
        })
      })
    } finally {
      if (originalElementFromPoint == null) {
        Reflect.deleteProperty(document, 'elementFromPoint')
      } else {
        document.elementFromPoint = originalElementFromPoint
      }
    }
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
        reportShellError={() => {}}
      />
    )
    await user.click(screen.getByRole('button', { name: 'Expand Territory options' }))
    const byTeam = screen.getByRole('checkbox', { name: 'By team' })
    expect(byTeam).not.toBeChecked()
    await user.click(byTeam)
    expect(byTeam).not.toBeChecked()
    expect(useTeamInformationPreferencesStore.getState().byTeamByGameId).toEqual({})
  })

  it('builds turns 1 through the game turn and opens the document', async () => {
    const user = userEvent.setup()
    useShellStore.setState({
      gameInfoContext: {
        ...useShellStore.getState().gameInfoContext!,
        turn: 9,
        perspectives: [perspectiveRow(1, 'ada', { playerId: 1, eliminationTurn: 2 })],
      },
    })
    vi.mocked(prepareTerritoryMovie).mockResolvedValue('<!DOCTYPE html><title>1</title>')
    renderTile(
      <TeamInformationMapTile
        name="Territory"
        enabled
        supportsMode
        depressed
        onToggle={() => {}}
        analyticScope={sampleScope}
        turnDataReady
        reportShellError={() => {}}
      />
    )
    await user.click(screen.getByRole('button', { name: 'Expand Territory options' }))
    await user.click(screen.getByRole('button', { name: 'Generate movie' }))
    await waitFor(() => {
      expect(prepareTerritoryMovie).toHaveBeenCalledWith({
        gameId: '628580',
        perspective: 1,
        gameTurn: 9,
        username: 'alice',
      })
    })
    expect(reserveTerritoryMovieWindow).toHaveBeenCalledTimes(1)
    expect(showTerritoryMovieDocument).toHaveBeenCalledWith(
      expect.anything(),
      '<!DOCTYPE html><title>1</title>'
    )
  })

  it('disables the movie button while the file is built', async () => {
    const user = userEvent.setup()
    let resolveMovie: (html: string) => void = () => {}
    vi.mocked(prepareTerritoryMovie).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveMovie = resolve
        })
    )
    renderTile(
      <TeamInformationMapTile
        name="Territory"
        enabled
        supportsMode
        depressed
        onToggle={() => {}}
        analyticScope={sampleScope}
        turnDataReady
        reportShellError={() => {}}
      />
    )
    await user.click(screen.getByRole('button', { name: 'Expand Territory options' }))
    await user.click(screen.getByRole('button', { name: 'Generate movie' }))
    expect(screen.getByRole('button', { name: 'Generate movie' })).toBeDisabled()
    resolveMovie('<!DOCTYPE html>')
    await waitFor(() => {
      expect(showTerritoryMovieDocument).toHaveBeenCalledWith(expect.anything(), '<!DOCTYPE html>')
    })
    expect(screen.getByRole('button', { name: 'Generate movie' })).toBeEnabled()
  })

  it('reports a failed ensure on the shell error bar and closes the blank window', async () => {
    const user = userEvent.setup()
    const reportShellError = vi.fn()
    const reserved = { close: vi.fn(), closed: false } as unknown as Window
    vi.mocked(reserveTerritoryMovieWindow).mockReturnValue(reserved)
    vi.mocked(prepareTerritoryMovie).mockRejectedValue(new Error('Ensure failed'))
    renderTile(
      <TeamInformationMapTile
        name="Territory"
        enabled
        supportsMode
        depressed
        onToggle={() => {}}
        analyticScope={sampleScope}
        turnDataReady
        reportShellError={reportShellError}
      />
    )
    await user.click(screen.getByRole('button', { name: 'Expand Territory options' }))
    await user.click(screen.getByRole('button', { name: 'Generate movie' }))
    await waitFor(() => {
      expect(reportShellError).toHaveBeenCalledWith('Ensure failed')
    })
    expect(reserveTerritoryMovieWindow).toHaveBeenCalledTimes(1)
    expect(showTerritoryMovieDocument).not.toHaveBeenCalled()
    expect(closeTerritoryMovieWindow).toHaveBeenCalledWith(reserved)
    expect(screen.getByRole('button', { name: 'Generate movie' })).toBeEnabled()
  })

  it('reports a missing game on the shell error bar and opens no window', async () => {
    const user = userEvent.setup()
    const reportShellError = vi.fn()
    renderTile(
      <TeamInformationMapTile
        name="Territory"
        enabled
        supportsMode
        depressed
        onToggle={() => {}}
        analyticScope={null}
        turnDataReady
        reportShellError={reportShellError}
      />
    )
    await user.click(screen.getByRole('button', { name: 'Expand Territory options' }))
    await user.click(screen.getByRole('button', { name: 'Generate movie' }))
    expect(reportShellError).toHaveBeenCalledWith(
      'Choose a game and viewpoint before opening the Territory movie.'
    )
    expect(prepareTerritoryMovie).not.toHaveBeenCalled()
    expect(reserveTerritoryMovieWindow).not.toHaveBeenCalled()
    expect(showTerritoryMovieDocument).not.toHaveBeenCalled()
  })

  it('reports a blocked window on the shell error bar and does not build the file', async () => {
    const user = userEvent.setup()
    const reportShellError = vi.fn()
    vi.mocked(reserveTerritoryMovieWindow).mockImplementation(() => {
      throw new Error('The browser blocked the Territory movie window.')
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
        reportShellError={reportShellError}
      />
    )
    await user.click(screen.getByRole('button', { name: 'Expand Territory options' }))
    await user.click(screen.getByRole('button', { name: 'Generate movie' }))
    expect(reportShellError).toHaveBeenCalledWith('The browser blocked the Territory movie window.')
    expect(prepareTerritoryMovie).not.toHaveBeenCalled()
    expect(showTerritoryMovieDocument).not.toHaveBeenCalled()
  })
})
