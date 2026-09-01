import { HomeworldLocatorTile } from './HomeworldLocatorTile'
import { sidebarTileChrome, type ShellAnalyticChrome } from '../shellAnalyticRegistry'

export const homeworldLocatorShellAnalytic: ShellAnalyticChrome = {
  renderSidebar(ctx) {
    return (
      <HomeworldLocatorTile
        {...sidebarTileChrome(ctx)}
        turnDataReady={ctx.turnDataReady}
        analyticScope={ctx.analyticScope}
      />
    )
  },
  availability(gameInfo) {
    return gameInfo?.homeworldInactiveReason ?? null
  },
}
