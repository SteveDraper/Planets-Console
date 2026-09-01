import type { ComponentType, ReactNode } from 'react'
import type { AnalyticItem, AnalyticShellScope } from '../api/bff'
import type { GameInfoShellContext } from '../stores/shell'
import { connectionsShellAnalytic } from './connections/shell'
import { fleetShellAnalytic } from './fleet/shell'
import { homeworldLocatorShellAnalytic } from './homeworld-locator/shell'
import {
  CONNECTIONS_ANALYTIC_ID,
  FLEET_ANALYTIC_ID,
  HOMEWORLD_LOCATOR_ANALYTIC_ID,
  STELLAR_CARTOGRAPHY_ANALYTIC_ID,
  VISIBILITY_ANALYTIC_ID,
} from './mapAnalyticIds'
import { SCORES_ANALYTIC_ID } from './scores/api'
import { scoresShellAnalytic } from './scores/shell'
import { stellarCartographyShellAnalytic } from './stellar-cartography/shell'
import { visibilityShellAnalytic } from './visibility/shell'

export type ShellViewMode = 'tabular' | 'map'

/**
 * Shell-owned inputs for a sidebar factory. Tiles read their own stores for
 * analytic-specific extras; `turnDataReady` and `analyticScope` are shell gates.
 */
export type ShellAnalyticSidebarContext = {
  viewMode: ShellViewMode
  catalogItem: AnalyticItem
  enabled: boolean
  onToggle: () => void
  turnDataReady: boolean
  analyticScope: AnalyticShellScope | null
}

export type ShellAnalyticTableViewProps = {
  analyticId: string
  analyticScope: AnalyticShellScope | null
  fetchEnabled: boolean
}

export type ShellAnalyticQueryParamAdapters = {
  appendTable?: (params: URLSearchParams) => void
  appendMap?: (params: URLSearchParams) => void
}

export type ShellLivedStreamSlot = {
  lifetime: 'shell'
  hook: (analyticScope: AnalyticShellScope | null, enabled: boolean) => object
  Provider: ComponentType<object & { children: ReactNode }>
}

export type TileLivedStreamSlot = {
  lifetime: 'tile'
}

export type ShellAnalyticStreamSlot = ShellLivedStreamSlot | TileLivedStreamSlot

/**
 * Sparse SPA plugin for one turn analytic's Shell chrome.
 * Omit a slot (or the whole registration) to keep generic checkbox / generic table.
 */
export type ShellAnalyticRegistration = {
  renderSidebar?: (ctx: ShellAnalyticSidebarContext) => ReactNode | null
  TableView?: ComponentType<ShellAnalyticTableViewProps>
  queryParams?: ShellAnalyticQueryParamAdapters
  availability?: (gameInfo: GameInfoShellContext | null) => string | null
  stream?: ShellAnalyticStreamSlot
}

const shellAnalyticRegistry: Record<string, ShellAnalyticRegistration> = {
  [SCORES_ANALYTIC_ID]: scoresShellAnalytic,
  [CONNECTIONS_ANALYTIC_ID]: connectionsShellAnalytic,
  [STELLAR_CARTOGRAPHY_ANALYTIC_ID]: stellarCartographyShellAnalytic,
  [FLEET_ANALYTIC_ID]: fleetShellAnalytic,
  [VISIBILITY_ANALYTIC_ID]: visibilityShellAnalytic,
  [HOMEWORLD_LOCATOR_ANALYTIC_ID]: homeworldLocatorShellAnalytic,
}

/** Selectable catalog ids that currently ship custom Shell chrome. */
export const CUSTOM_SHELL_CHROME_ANALYTIC_IDS = [
  SCORES_ANALYTIC_ID,
  CONNECTIONS_ANALYTIC_ID,
  STELLAR_CARTOGRAPHY_ANALYTIC_ID,
  FLEET_ANALYTIC_ID,
  VISIBILITY_ANALYTIC_ID,
  HOMEWORLD_LOCATOR_ANALYTIC_ID,
] as const satisfies readonly string[]

export type CustomShellChromeAnalyticId = (typeof CUSTOM_SHELL_CHROME_ANALYTIC_IDS)[number]

export function isRegisteredShellAnalytic(analyticId: string): boolean {
  return Object.prototype.hasOwnProperty.call(shellAnalyticRegistry, analyticId)
}

/** Sparse lookup: missing id is generic chrome, not an error. */
export function shellAnalyticRegistrationFor(
  analyticId: string
): ShellAnalyticRegistration | undefined {
  return shellAnalyticRegistry[analyticId]
}

export function analyticSupportsViewMode(
  catalogItem: AnalyticItem,
  viewMode: ShellViewMode
): boolean {
  return viewMode === 'tabular' ? catalogItem.supportsTable : catalogItem.supportsMap
}

/**
 * Drop enabled ids whose registration reports a GameInfo inactivity reason.
 * Persisted enablement is left intact.
 */
export function foldAvailableEnabledAnalyticIds(
  enabledAnalyticIds: readonly string[],
  gameInfo: GameInfoShellContext | null
): string[] {
  return enabledAnalyticIds.filter((analyticId) => {
    const reason = shellAnalyticRegistrationFor(analyticId)?.availability?.(gameInfo) ?? null
    return reason == null
  })
}

export function shellLivedStreamRegistrations(): Array<{
  analyticId: string
  stream: ShellLivedStreamSlot
}> {
  return Object.entries(shellAnalyticRegistry).flatMap(([analyticId, registration]) => {
    const stream = registration.stream
    if (stream == null || stream.lifetime !== 'shell') {
      return []
    }
    return [{ analyticId, stream }]
  })
}
