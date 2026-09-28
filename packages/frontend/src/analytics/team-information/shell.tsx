import { TeamInformationMapTile } from './TeamInformationMapTile'
import { sidebarTileChrome, type ShellAnalyticChrome } from '../shellAnalyticRegistry'

export const teamInformationShellAnalytic: ShellAnalyticChrome = {
  renderSidebar(ctx) {
    return (
      <TeamInformationMapTile
        {...sidebarTileChrome(ctx)}
        analyticScope={ctx.analyticScope}
        turnDataReady={ctx.turnDataReady}
      />
    )
  },
}
