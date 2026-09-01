import { ScoresTableTile } from './ScoresTableTile'
import { ScoresAnalyticTableTile } from './ScoresAnalyticTableTile'
import { sidebarTileChrome, type ShellAnalyticChrome } from '../shellAnalyticRegistry'

export const scoresShellAnalytic: ShellAnalyticChrome = {
  renderSidebar(ctx) {
    if (ctx.viewMode !== 'tabular') {
      return null
    }
    return (
      <ScoresTableTile
        {...sidebarTileChrome(ctx)}
        turnDataReady={ctx.turnDataReady}
        analyticScope={ctx.analyticScope}
      />
    )
  },
  TableView: ScoresAnalyticTableTile,
  stream: { lifetime: 'tile' },
}
