import { ScoresTableTile } from './ScoresTableTile'
import { ScoresAnalyticTableTile } from './ScoresAnalyticTableTile'
import { appendScoresTableQueryParamsFromStore } from './queryParams'
import type { ShellAnalyticRegistration } from '../shellAnalyticRegistry'

export const scoresShellAnalytic: ShellAnalyticRegistration = {
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
  queryParams: { appendTable: appendScoresTableQueryParamsFromStore },
  stream: { lifetime: 'tile' },
}
