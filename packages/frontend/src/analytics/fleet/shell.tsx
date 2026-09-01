import { FleetAnalyticTile } from './FleetAnalyticTile'
import { FleetAnalyticTableTile } from './FleetAnalyticTableTile'
import { FleetStreamPlayersProvider } from './FleetStreamPlayersContext'
import { useFleetTableStream } from './useFleetTableStream'
import type { ShellAnalyticRegistration, ShellLivedStreamSlot } from '../shellAnalyticRegistry'

const fleetShellLivedStream: ShellLivedStreamSlot = {
  lifetime: 'shell',
  hook: useFleetTableStream,
  Provider: FleetStreamPlayersProvider as ShellLivedStreamSlot['Provider'],
}

export const fleetShellAnalytic: ShellAnalyticRegistration = {
  renderSidebar(ctx) {
    const supportsMode =
      ctx.viewMode === 'tabular' ? ctx.catalogItem.supportsTable : ctx.catalogItem.supportsMap
    return (
      <FleetAnalyticTile
        name={ctx.catalogItem.name}
        enabled={ctx.enabled}
        supportsMode={supportsMode}
        depressed={ctx.enabled && supportsMode}
        onToggle={ctx.onToggle}
      />
    )
  },
  TableView({ analyticScope, fetchEnabled }) {
    return (
      <FleetAnalyticTableTile analyticScope={analyticScope} fetchEnabled={fetchEnabled} />
    )
  },
  stream: fleetShellLivedStream,
}
