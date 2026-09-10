import { MinefieldsMapTile } from './MinefieldsMapTile'
import { sidebarTileChrome, type ShellAnalyticChrome } from '../shellAnalyticRegistry'

export const minefieldsShellAnalytic: ShellAnalyticChrome = {
  renderSidebar(ctx) {
    return <MinefieldsMapTile {...sidebarTileChrome(ctx)} />
  },
  availability(gameInfo) {
    return gameInfo?.minefieldsInactiveReason ?? null
  },
}
