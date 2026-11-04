import { shellLivedStream } from '../shellLivedStream'
import { sidebarTileChrome, type ShellAnalyticChrome } from '../shellAnalyticRegistry'
import { HomeworldFleetAgeRefetchFrame } from './HomeworldFleetAgeRefetchFrame'
import { HomeworldLocatorTile } from './HomeworldLocatorTile'
import { useHomeworldFleetAgeRefetch } from './useHomeworldFleetAgeRefetch'

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
  stream: shellLivedStream({
    hook: useHomeworldFleetAgeRefetch,
    Provider: HomeworldFleetAgeRefetchFrame,
  }),
}
