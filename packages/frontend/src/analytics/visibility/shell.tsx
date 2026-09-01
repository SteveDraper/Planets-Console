import { VisibilityMapTile } from './VisibilityMapTile'
import { sidebarTileChrome, type ShellAnalyticChrome } from '../shellAnalyticRegistry'

export const visibilityShellAnalytic: ShellAnalyticChrome = {
  renderSidebar(ctx) {
    if (ctx.viewMode !== 'map') {
      return null
    }
    return <VisibilityMapTile {...sidebarTileChrome(ctx)} />
  },
}
