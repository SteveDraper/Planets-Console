import { HomeworldLocatorTile } from './HomeworldLocatorTile'
import type { ShellAnalyticChrome } from '../shellAnalyticRegistry'

export const homeworldLocatorShellAnalytic: ShellAnalyticChrome = {
  renderSidebar(ctx) {
    const supportsMode =
      ctx.viewMode === 'tabular' ? ctx.catalogItem.supportsTable : ctx.catalogItem.supportsMap
    return (
      <HomeworldLocatorTile
        name={ctx.catalogItem.name}
        enabled={ctx.enabled}
        supportsMode={supportsMode}
        depressed={ctx.enabled && supportsMode}
        onToggle={ctx.onToggle}
        turnDataReady={ctx.turnDataReady}
      />
    )
  },
  availability(gameInfo) {
    return gameInfo?.homeworldInactiveReason ?? null
  },
}
