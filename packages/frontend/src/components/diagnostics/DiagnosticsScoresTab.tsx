import { ClipboardCopy } from 'lucide-react'
import type { ScoresInferenceRowDetail } from '../../api/bff'
import type {
  ScoresAnalyticDiagnostics,
  ScoresPlayerInferenceDiagnostics,
} from '../../stores/analyticDiagnostics'
import { cn } from '../../lib/utils'
import { DiagnosticsJsonBlock } from './DiagnosticsJsonBlock'
import { FleetTorpInputStatusDetail } from '../../analytics/scores/FleetTorpInputStatusDetail'

function inferenceDetailFromDiagnosticsPlayer(
  player: ScoresPlayerInferenceDiagnostics
): ScoresInferenceRowDetail {
  return {
    playerId: player.playerId,
    displayStatus: 'success',
    status: player.status,
    summary: player.summary,
    solutionCount: 0,
    isComplete: true,
    solutions: [],
    diagnostics: player.diagnostics,
    fleetTorpInputStatus: player.fleetTorpInputStatus,
    fleetTorpOverlayBeliefSetTorpIds: player.fleetTorpOverlayBeliefSetTorpIds,
  }
}

type DiagnosticsScoresTabProps = {
  snapshot: ScoresAnalyticDiagnostics | null
  onCopy: (text: string) => void
}

export function DiagnosticsScoresTab({ snapshot, onCopy }: DiagnosticsScoresTabProps) {
  if (snapshot == null) {
    return (
      <p className="text-sm text-slate-400">
        No scores solver diagnostics yet. Enable{' '}
        <span className="font-medium text-slate-300">Scores</span> with{' '}
        <span className="font-medium text-slate-300">Include build inference</span>, then load
        the scoreboard table.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="rounded border border-[#52575d] bg-[#40454a] p-3 text-xs text-slate-300">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p>
              Game <span className="font-medium text-slate-200">{snapshot.scope.gameId}</span>
              {' · '}
              Turn <span className="font-medium text-slate-200">{snapshot.scope.turn}</span>
              {' · '}
              Perspective{' '}
              <span className="font-medium text-slate-200">{snapshot.scope.perspective}</span>
            </p>
            <p className="mt-1 text-slate-500">Captured {snapshot.capturedAt}</p>
          </div>
          <button
            type="button"
            onClick={() => onCopy(JSON.stringify(snapshot, null, 2))}
            className={cn(
              'inline-flex shrink-0 items-center gap-1 rounded p-1 text-slate-300',
              'hover:bg-white/10 focus:outline-none focus:ring-1 focus:ring-slate-400'
            )}
            title="Copy scores diagnostics"
            aria-label="Copy scores diagnostics"
          >
            <ClipboardCopy className="h-3.5 w-3.5" aria-hidden />
          </button>
        </div>
      </div>

      {snapshot.players.map((player) => (
        <section
          key={player.playerId}
          className="rounded border border-[#52575d] bg-[#40454a] p-3"
        >
          <div className="mb-2 flex items-start justify-between gap-2">
            <div>
              <h3 className="text-xs font-medium text-slate-200">{player.racePlayer}</h3>
              <p className="mt-0.5 text-xs text-slate-400">
                Player {player.playerId} · Turn {player.turn} · {player.status}
              </p>
              <p className="mt-1 text-xs text-slate-300">{player.summary}</p>
              <FleetTorpInputStatusDetail
                detail={inferenceDetailFromDiagnosticsPlayer(player)}
                variant="inline"
              />
            </div>
            <button
              type="button"
              onClick={() => onCopy(JSON.stringify(player, null, 2))}
              className={cn(
                'inline-flex shrink-0 items-center gap-1 rounded p-1 text-slate-300',
                'hover:bg-white/10 focus:outline-none focus:ring-1 focus:ring-slate-400'
              )}
              title="Copy player diagnostics"
              aria-label={`Copy diagnostics for ${player.racePlayer}`}
            >
              <ClipboardCopy className="h-3.5 w-3.5" aria-hidden />
            </button>
          </div>

          <div className="flex flex-col gap-2">
            <div>
              <h4 className="mb-1 text-[11px] font-medium uppercase tracking-wide text-slate-500">
                Constraints
              </h4>
              <DiagnosticsJsonBlock
                value={player.constraints}
                emptyLabel="No constraint data in the latest scores response."
              />
            </div>
            <div>
              <h4 className="mb-1 text-[11px] font-medium uppercase tracking-wide text-slate-500">
                Action catalog
              </h4>
              <DiagnosticsJsonBlock
                value={player.actionCatalog}
                emptyLabel="No action catalog data in the latest scores response."
              />
            </div>
            <div>
              <h4 className="mb-1 text-[11px] font-medium uppercase tracking-wide text-slate-500">
                Solver
              </h4>
              <DiagnosticsJsonBlock
                value={player.solver}
                emptyLabel="No solver data in the latest scores response."
              />
            </div>
          </div>
        </section>
      ))}
    </div>
  )
}
