import { ScoresTableTile } from './ScoresTableTile'
import { ScoresAnalyticTableTile } from './ScoresAnalyticTableTile'
import type { ShellAnalyticChrome } from '../shellAnalyticRegistry'

export const scoresShellAnalytic: ShellAnalyticChrome = {
  renderSidebar(ctx) {
    if (ctx.viewMode !== 'tabular') {
      return null
    }
    const supportsMode = ctx.catalogItem.supportsTable
    return (
      <ScoresTableTile
        name={ctx.catalogItem.name}
        enabled={ctx.enabled}
        supportsMode={supportsMode}
        depressed={ctx.enabled && supportsMode}
        onToggle={ctx.onToggle}
        turnDataReady={ctx.turnDataReady}
        analyticScope={ctx.analyticScope}
      />
    )
  },
  TableView: ScoresAnalyticTableTile,
  stream: { lifetime: 'tile' },
}
