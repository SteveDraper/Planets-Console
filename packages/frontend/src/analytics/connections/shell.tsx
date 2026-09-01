import { ConnectionsMapTile } from './ConnectionsMapTile'
import { sidebarTileChrome, type ShellAnalyticChrome } from '../shellAnalyticRegistry'

export const connectionsShellAnalytic: ShellAnalyticChrome = {
  renderSidebar(ctx) {
    if (ctx.viewMode !== 'map') {
      return null
    }
    return <ConnectionsMapTile {...sidebarTileChrome(ctx)} />
  },
}
