import { StellarCartographyMapTile } from './StellarCartographyMapTile'
import { sidebarTileChrome, type ShellAnalyticChrome } from '../shellAnalyticRegistry'

export const stellarCartographyShellAnalytic: ShellAnalyticChrome = {
  renderSidebar(ctx) {
    if (ctx.viewMode !== 'map') {
      return null
    }
    return (
      <StellarCartographyMapTile
        {...sidebarTileChrome(ctx)}
        turnDataReady={ctx.turnDataReady}
        analyticScope={ctx.analyticScope}
      />
    )
  },
}
