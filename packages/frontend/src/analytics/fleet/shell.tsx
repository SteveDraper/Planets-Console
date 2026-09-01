import { FleetAnalyticTile } from './FleetAnalyticTile'
import { FleetAnalyticTableTile } from './FleetAnalyticTableTile'
import { FleetStreamPlayersProvider } from './FleetStreamPlayersContext'
import { useFleetTableStream } from './useFleetTableStream'
import { shellLivedStream } from '../shellLivedStream'
import { sidebarTileChrome, type ShellAnalyticChrome } from '../shellAnalyticRegistry'

export const fleetShellAnalytic: ShellAnalyticChrome = {
  renderSidebar(ctx) {
    return (
      <FleetAnalyticTile
        {...sidebarTileChrome(ctx)}
        analyticScope={ctx.analyticScope}
      />
    )
  },
  TableView({ analyticScope, fetchEnabled }) {
    return (
      <FleetAnalyticTableTile analyticScope={analyticScope} fetchEnabled={fetchEnabled} />
    )
  },
  stream: shellLivedStream({
    hook: useFleetTableStream,
    Provider: FleetStreamPlayersProvider,
  }),
}
