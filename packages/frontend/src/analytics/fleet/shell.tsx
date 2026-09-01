import { FleetAnalyticTile } from './FleetAnalyticTile'
import { FleetAnalyticTableTile } from './FleetAnalyticTableTile'
import { FleetStreamPlayersProvider } from './FleetStreamPlayersContext'
import { useFleetTableStream } from './useFleetTableStream'
import {
  sidebarTileChrome,
  type ShellAnalyticChrome,
  type ShellLivedStreamSlot,
} from '../shellAnalyticRegistry'

const fleetShellLivedStream: ShellLivedStreamSlot = {
  lifetime: 'shell',
  hook: useFleetTableStream,
  Provider: FleetStreamPlayersProvider as ShellLivedStreamSlot['Provider'],
}

export const fleetShellAnalytic: ShellAnalyticChrome = {
  renderSidebar(ctx) {
    return <FleetAnalyticTile {...sidebarTileChrome(ctx)} />
  },
  TableView({ analyticScope, fetchEnabled }) {
    return (
      <FleetAnalyticTableTile analyticScope={analyticScope} fetchEnabled={fetchEnabled} />
    )
  },
  stream: fleetShellLivedStream,
}
