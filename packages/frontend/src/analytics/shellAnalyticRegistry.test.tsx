import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import type { AnalyticItem } from '../api/bff'
import { GenericTableTile } from './GenericTableTile'
import { renderShellAnalyticSidebar } from './renderShellAnalyticSidebar'
import {
  CUSTOM_SHELL_CHROME_ANALYTIC_IDS,
  foldAvailableEnabledAnalyticIds,
  isRegisteredShellAnalytic,
  shellAnalyticRegistrationFor,
  shellLivedStreamRegistrations,
  sidebarTileChrome,
} from './shellAnalyticRegistry'
import { SHELL_MAP_QUERY_APPENDERS, SHELL_TABLE_QUERY_APPENDERS } from './shellAnalyticQueryParams'
import { SCORES_ANALYTIC_ID } from './scores/api'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from './stellar-cartography/layers'

const SELECTABLE_TURN_ANALYTIC_IDS = [
  'scores',
  'connections',
  'stellar-cartography',
  'fleet',
  'visibility',
  'homeworld-locator',
] as const

const UNREGISTERED_SELECTABLE: AnalyticItem = {
  id: 'unregistered-selectable',
  name: 'Unregistered',
  supportsTable: true,
  supportsMap: false,
  type: 'selectable',
}

function renderWithQuery(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(ui, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  })
}

describe('shell analytic registry', () => {
  it('lists every selectable catalog id that currently has custom chrome', () => {
    expect([...CUSTOM_SHELL_CHROME_ANALYTIC_IDS]).toEqual([...SELECTABLE_TURN_ANALYTIC_IDS])
    for (const analyticId of CUSTOM_SHELL_CHROME_ANALYTIC_IDS) {
      expect(isRegisteredShellAnalytic(analyticId)).toBe(true)
      expect(shellAnalyticRegistrationFor(analyticId)).toBeDefined()
    }
  })

  it('does not treat an unknown selectable id as an error', () => {
    expect(isRegisteredShellAnalytic(UNREGISTERED_SELECTABLE.id)).toBe(false)
    expect(shellAnalyticRegistrationFor(UNREGISTERED_SELECTABLE.id)).toBeUndefined()
  })

  it('falls back to a generic checkbox for an unregistered selectable id', () => {
    const { getByRole, getByText } = renderWithQuery(
      renderShellAnalyticSidebar({
        viewMode: 'tabular',
        catalogItem: UNREGISTERED_SELECTABLE,
        enabled: false,
        onToggle: () => {},
        turnDataReady: true,
        analyticScope: null,
      })
    )
    expect(getByRole('checkbox')).toBeInTheDocument()
    expect(getByText('Unregistered')).toBeInTheDocument()
  })

  it('falls back to generic table for an unregistered selectable id', () => {
    const { getByText } = renderWithQuery(
      <GenericTableTile
        analyticId={UNREGISTERED_SELECTABLE.id}
        analyticScope={null}
        fetchEnabled={false}
      />
    )
    expect(
      getByText(/load game info and choose a turn and viewpoint/i)
    ).toBeInTheDocument()
  })

  it('composes every queryParams slot from the React-free fetch maps, and vice versa', () => {
    for (const analyticId of CUSTOM_SHELL_CHROME_ANALYTIC_IDS) {
      const queryParams = shellAnalyticRegistrationFor(analyticId)?.queryParams
      expect(queryParams?.appendTable).toBe(SHELL_TABLE_QUERY_APPENDERS[analyticId])
      expect(queryParams?.appendMap).toBe(SHELL_MAP_QUERY_APPENDERS[analyticId])
    }
    for (const analyticId of Object.keys(SHELL_TABLE_QUERY_APPENDERS)) {
      expect(shellAnalyticRegistrationFor(analyticId)?.queryParams?.appendTable).toBe(
        SHELL_TABLE_QUERY_APPENDERS[analyticId]
      )
    }
    for (const analyticId of Object.keys(SHELL_MAP_QUERY_APPENDERS)) {
      expect(shellAnalyticRegistrationFor(analyticId)?.queryParams?.appendMap).toBe(
        SHELL_MAP_QUERY_APPENDERS[analyticId]
      )
    }
  })

  it('records fleet as shell-lived and scores as tile-lived', () => {
    const shellLived = shellLivedStreamRegistrations().map((row) => row.analyticId)
    expect(shellLived).toEqual(['fleet'])
    expect(shellAnalyticRegistrationFor(SCORES_ANALYTIC_ID)?.stream?.lifetime).toBe('tile')
  })

  it('folds GameInfo unavailability without an id-specific App branch', () => {
    expect(
      foldAvailableEnabledAnalyticIds(['scores', 'homeworld-locator'], {
        turn: 1,
        perspectives: [],
        isGameFinished: true,
        sectorDisplayName: null,
        stellarCartographyGates: EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
        homeworldInactiveReason: 'nohomeworld',
      })
    ).toEqual(['scores'])
  })
})

describe('shell dispatch has no analytic id branches', () => {
  const here = dirname(fileURLToPath(import.meta.url))
  const srcRoot = join(here, '..')
  const idBranch = /\b(?:analyticId|a\.id|\.id|id)\s*===\s*['`](?:scores|connections|stellar-cartography|fleet|visibility|homeworld-locator)['`]/

  it('keeps App, AnalyticsBar, MainArea, and generic table/map fetch free of id switches', () => {
    const app = readFileSync(join(srcRoot, 'App.tsx'), 'utf8')
    const bar = readFileSync(join(srcRoot, 'components/AnalyticsBar.tsx'), 'utf8')
    const main = readFileSync(join(srcRoot, 'components/MainArea.tsx'), 'utf8')
    const bff = readFileSync(join(srcRoot, 'api/bff.ts'), 'utf8')
    expect(app).not.toMatch(idBranch)
    expect(bar).not.toMatch(idBranch)
    expect(main).not.toMatch(idBranch)
    const tableFn = bff.slice(bff.indexOf('export async function fetchAnalyticTable'))
    const mapFn = bff.slice(bff.indexOf('export async function fetchAnalyticMap'))
    const tableBody = tableFn.slice(0, tableFn.indexOf('export async function fetchScoresRowInference'))
    const mapBody = mapFn.slice(0, mapFn.indexOf('export async function fetchStellarCartographySample'))
    expect(tableBody).not.toMatch(idBranch)
    expect(mapBody).not.toMatch(idBranch)
  })

  it('does not author queryParams on shell.tsx modules', () => {
    for (const analyticId of CUSTOM_SHELL_CHROME_ANALYTIC_IDS) {
      const source = readFileSync(join(here, analyticId, 'shell.tsx'), 'utf8')
      expect(source).not.toMatch(/\bqueryParams\s*:/)
    }
  })
})

describe('sidebarTileChrome', () => {
  const here = dirname(fileURLToPath(import.meta.url))
  const catalogItem: AnalyticItem = {
    id: 'example',
    name: 'Example',
    supportsTable: true,
    supportsMap: false,
    type: 'selectable',
  }
  const onToggle = () => {}

  it('uses analyticSupportsViewMode for greying and depression', () => {
    expect(
      sidebarTileChrome({
        viewMode: 'tabular',
        catalogItem,
        enabled: true,
        onToggle,
        turnDataReady: true,
        analyticScope: null,
      })
    ).toEqual({
      name: 'Example',
      enabled: true,
      supportsMode: true,
      depressed: true,
      onToggle,
    })
    expect(
      sidebarTileChrome({
        viewMode: 'map',
        catalogItem,
        enabled: true,
        onToggle,
        turnDataReady: true,
        analyticScope: null,
      })
    ).toEqual({
      name: 'Example',
      enabled: true,
      supportsMode: false,
      depressed: false,
      onToggle,
    })
  })

  it('does not depress when the analytic is disabled', () => {
    expect(
      sidebarTileChrome({
        viewMode: 'tabular',
        catalogItem,
        enabled: false,
        onToggle,
        turnDataReady: true,
        analyticScope: null,
      }).depressed
    ).toBe(false)
  })

  it('is the chrome mapping used by every shell factory and the generic fallback', () => {
    for (const analyticId of CUSTOM_SHELL_CHROME_ANALYTIC_IDS) {
      const source = readFileSync(join(here, analyticId, 'shell.tsx'), 'utf8')
      expect(source).toMatch(/\{\.\.\.sidebarTileChrome\(ctx\)\}/)
      expect(source).not.toMatch(/\bsupportsMode\s*=/)
    }
    const fallback = readFileSync(join(here, 'renderShellAnalyticSidebar.tsx'), 'utf8')
    expect(fallback).toMatch(/sidebarTileChrome\(ctx\)/)
    expect(fallback).not.toMatch(/\bsupportsMode\s*=/)
  })
})
