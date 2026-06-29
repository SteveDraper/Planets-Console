import { useCallback, useLayoutEffect, useRef } from 'react'
import type { ScoresInferenceRowDetail, ScoresInferenceSolution } from '../../api/bff'
import { useModalKeydownFocusTrap } from '../../lib/modalKeydownFocusTrap'
import { restoreFocusToElementOrFallback } from '../../lib/restoreFocus'
import { cn } from '../../lib/utils'
import {
  formatSignedDelta,
  militaryChangeFromDelta2x,
  readInferenceConstraints,
  readMilitaryScoreArithmetic,
  type MilitaryScoreArithmetic,
} from './inferenceConstraints'
import { InferenceSolutionLineIcon } from './inferenceSolutionLineIcon'
import { readInferenceRunSummary } from './inferenceRunSummary'
import { FleetTorpInputStatusDetail } from './FleetTorpInputStatusDetail'
import { isRecord } from './scoresWireParsers'
import {
  formatSolutionLineItemLabel,
  sortSolutionLineItemsForDisplay,
} from './solutionLineItemDisplayOrder'

type InferenceDetailModalProps = {
  isOpen: boolean
  onClose: () => void
  racePlayer: string
  detail: ScoresInferenceRowDetail | null
  isGloballyPaused?: boolean
}

function SolutionActionTable({
  solution,
  arithmetic,
}: {
  solution: ScoresInferenceSolution
  arithmetic: MilitaryScoreArithmetic
}) {
  const displayLineItems = sortSolutionLineItemsForDisplay(arithmetic.lineItems)

  return (
    <div className="mt-2 overflow-x-auto">
      <table className="w-full border-collapse text-xs text-slate-300">
        <thead>
          <tr className="border-b border-[#52575d]/60 text-left text-slate-400">
            <th className="w-10 py-1 pr-2">
              <span className="sr-only">Icon</span>
            </th>
            <th className="py-1 pr-2 font-medium">Action</th>
            <th className="py-1 font-medium">Military</th>
          </tr>
        </thead>
        <tbody>
          {displayLineItems.map((line) => (
            <tr key={line.actionId} className="border-b border-[#52575d]/40">
              <td className="py-1 pr-2 align-middle">
                <InferenceSolutionLineIcon line={line} shipBuilds={solution.shipBuilds} />
              </td>
              <td className="py-1 pr-2">{formatSolutionLineItemLabel(line)}</td>
              <td className="py-1 tabular-nums">
                {formatSignedDelta(line.militaryChangeSubtotal)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 space-y-1 border-t border-[#52575d]/40 pt-2 text-xs">
        <div className="flex justify-between gap-4 text-slate-200">
          <span>Explained military change</span>
          <span className="tabular-nums font-medium">
            {formatSignedDelta(arithmetic.explainedMilitaryChange)}
          </span>
        </div>
        <div className="flex justify-between gap-4 text-slate-400">
          <span>Observed military change</span>
          <span className="tabular-nums">
            {formatSignedDelta(arithmetic.observedMilitaryChange)}
          </span>
        </div>
        {!arithmetic.matchesObserved ? (
          <p className="text-amber-300/90">
            Explained military change does not match the observed scoreboard delta.
          </p>
        ) : null}
      </div>
    </div>
  )
}

function SolutionSection({
  solution,
  index,
}: {
  solution: ScoresInferenceSolution
  index: number
}) {
  const arithmetic = readMilitaryScoreArithmetic(solution.militaryScoreArithmetic)
  return (
    <section className="rounded border border-[#52575d]/70 bg-[#2a2d30] p-3">
      <h3
        className="text-xs font-medium text-slate-200"
        title="Composite rank score from action priors and parsimony penalties -- not a percentage."
      >
        Solution {index + 1} · Plausibility {solution.objectiveValue}
      </h3>
      {arithmetic != null && arithmetic.lineItems.length > 0 ? (
        <SolutionActionTable solution={solution} arithmetic={arithmetic} />
      ) : (
        <ul className="mt-2 flex flex-col gap-1 text-xs text-slate-300">
          {solution.actions.map((action) => (
            <li key={action.actionId}>
              {action.count > 1 ? `${action.count}x ` : ''}
              {action.label}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function inferenceSearchBanner(
  detail: ScoresInferenceRowDetail,
  isGloballyPaused: boolean
): string | null {
  if (detail.isComplete) {
    return null
  }
  if (detail.displayStatus === 'paused' || isGloballyPaused) {
    return 'Search paused -- held explanations are current.'
  }
  return 'Search continuing -- more explanations may appear.'
}

export function InferenceDetailModal({
  isOpen,
  onClose,
  racePlayer,
  detail,
  isGloballyPaused = false,
}: InferenceDetailModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)

  const closeAndReturnFocus = useCallback(() => {
    const target = returnFocusRef.current
    onClose()
    restoreFocusToElementOrFallback(target, undefined)
  }, [onClose])

  useLayoutEffect(() => {
    if (!isOpen) return
    returnFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    const el = dialogRef.current
    if (!el) return
    const focusables = el.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    )
    focusables[0]?.focus()
  }, [isOpen])

  useModalKeydownFocusTrap(isOpen, dialogRef, closeAndReturnFocus)

  if (!isOpen || detail == null) return null

  const diagnostics = isRecord(detail.diagnostics) ? detail.diagnostics : {}
  const constraints = readInferenceConstraints(diagnostics)
  const inferenceRun = readInferenceRunSummary(detail, diagnostics)
  const scoreboardTurn = constraints?.turn
  const hostTurn =
    constraints?.hostTurn ??
    (scoreboardTurn != null && scoreboardTurn > 1 ? scoreboardTurn - 1 : null)
  const searchBanner = inferenceSearchBanner(detail, isGloballyPaused)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      aria-hidden="false"
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          closeAndReturnFocus()
        }
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="inference-detail-title"
        onClick={(e) => e.stopPropagation()}
        className={cn(
          'flex max-h-[min(90vh,40rem)] w-full max-w-2xl flex-col gap-3 overflow-y-auto',
          'rounded border border-[#52575d] bg-[#40454a] p-4 shadow-lg',
          'focus:outline-none'
        )}
      >
        <div className="flex items-start justify-between gap-2">
          <div>
            <h2 id="inference-detail-title" className="text-sm font-medium text-slate-200">
              Build inference
            </h2>
            <p className="mt-1 text-xs text-slate-400">{racePlayer}</p>
            {scoreboardTurn != null ? (
              <p className="mt-1 text-xs text-slate-400">
                Scoreboard row turn {scoreboardTurn}
                {hostTurn != null ? ` · Host turn ${hostTurn} deltas` : ''}
                {constraints?.playerId != null ? ` · Player ${constraints?.playerId}` : ''}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={closeAndReturnFocus}
            className="rounded px-2 py-1 text-xs text-slate-400 hover:bg-white/10 hover:text-slate-200"
          >
            Close
          </button>
        </div>

        {constraints != null ? (
          <section className="rounded border border-[#52575d]/70 bg-[#2a2d30] p-3">
            <h3 className="text-xs font-medium text-slate-200">Observed constraints</h3>
            <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs text-slate-300">
              {constraints.militaryDelta2x != null ? (
                <>
                  <dt className="text-slate-400">Military change</dt>
                  <dd className="tabular-nums">
                    {formatSignedDelta(
                      militaryChangeFromDelta2x(constraints.militaryDelta2x)
                    )}
                  </dd>
                </>
              ) : null}
              {constraints.warshipDelta != null ? (
                <>
                  <dt className="text-slate-400">Warship change</dt>
                  <dd className="tabular-nums">{formatSignedDelta(constraints.warshipDelta)}</dd>
                </>
              ) : null}
              {constraints.freighterDelta != null ? (
                <>
                  <dt className="text-slate-400">Freighter change</dt>
                  <dd className="tabular-nums">{formatSignedDelta(constraints.freighterDelta)}</dd>
                </>
              ) : null}
              {constraints.requestedPriorityPointDelta != null ? (
                <>
                  <dt className="text-slate-400">Priority point change</dt>
                  <dd className="tabular-nums">
                    {formatSignedDelta(constraints.requestedPriorityPointDelta)}
                  </dd>
                </>
              ) : null}
            </dl>
          </section>
        ) : null}

        <FleetTorpInputStatusDetail diagnostics={diagnostics} />

        {inferenceRun.statusLabel != null || inferenceRun.wallTimeSeconds != null ? (
          <p className="text-xs text-slate-500">
            {inferenceRun.statusLabel != null
              ? `Inference ${inferenceRun.statusLabel}`
              : 'Inference'}
            {inferenceRun.wallTimeSeconds != null
              ? ` · ${inferenceRun.wallTimeSeconds.toFixed(2)}s`
              : ''}
          </p>
        ) : null}

        {detail.solutions.length === 0 && detail.summary.trim().length > 0 ? (
          <p className="text-xs text-slate-300">{detail.summary}</p>
        ) : null}

        <div className="flex flex-col gap-3">
          {detail.solutions.map((solution, index) => (
            <SolutionSection key={`solution-${index}`} solution={solution} index={index} />
          ))}
        </div>

        {searchBanner != null ? (
          <p className="text-xs text-slate-400">{searchBanner}</p>
        ) : null}
      </div>
    </div>
  )
}
