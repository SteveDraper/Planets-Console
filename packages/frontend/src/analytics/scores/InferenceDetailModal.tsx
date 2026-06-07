import { useCallback, useLayoutEffect, useRef } from 'react'
import type { ScoresInferenceRowDetail, ScoresInferenceSolution } from '../../api/bff'
import { useModalKeydownFocusTrap } from '../../lib/modalKeydownFocusTrap'
import { restoreFocusToElementOrFallback } from '../../lib/restoreFocus'
import { cn } from '../../lib/utils'
import {
  acceleratedSegmentTitle,
  readAcceleratedInferenceSegments,
  type AcceleratedInferenceSegment,
} from './acceleratedInferenceSegments'
import {
  formatSignedDelta,
  militaryChangeFromDelta2x,
  readInferenceConstraints,
  readMilitaryScoreArithmetic,
  type MilitaryScoreArithmetic,
} from './inferenceConstraints'

type InferenceDetailModalProps = {
  isOpen: boolean
  onClose: () => void
  racePlayer: string
  detail: ScoresInferenceRowDetail | null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === 'object' && !Array.isArray(value)
}

function readSolverSummary(diagnostics: Record<string, unknown>): {
  status?: string
  wallTimeSeconds?: number
} {
  const solver = diagnostics.solver
  if (!isRecord(solver)) {
    return {}
  }
  const solverStatus =
    typeof solver.solver_status === 'string'
      ? solver.solver_status
      : typeof solver.solverStatus === 'string'
        ? solver.solverStatus
        : undefined
  return {
    status: solverStatus,
    wallTimeSeconds:
      typeof solver.wall_time_seconds === 'number'
        ? solver.wall_time_seconds
        : typeof solver.wallTimeSeconds === 'number'
          ? solver.wallTimeSeconds
          : undefined,
  }
}

function MilitaryScoreArithmeticTable({ arithmetic }: { arithmetic: MilitaryScoreArithmetic }) {
  return (
    <div className="mt-2 overflow-x-auto">
      <table className="w-full border-collapse text-xs text-slate-300">
        <thead>
          <tr className="border-b border-[#52575d]/60 text-left text-slate-400">
            <th className="py-1 pr-2 font-medium">Action</th>
            <th className="py-1 pr-2 font-medium">Count</th>
            <th className="py-1 pr-2 font-medium">Per unit</th>
            <th className="py-1 font-medium">Military subtotal</th>
          </tr>
        </thead>
        <tbody>
          {arithmetic.lineItems.map((line) => (
            <tr key={line.actionId} className="border-b border-[#52575d]/40">
              <td className="py-1 pr-2">{line.label}</td>
              <td className="py-1 pr-2 tabular-nums">{line.count}</td>
              <td className="py-1 pr-2 tabular-nums">
                {formatSignedDelta(line.militaryChangePerUnit)}
              </td>
              <td className="py-1 tabular-nums">
                {formatSignedDelta(line.militaryChangeSubtotal)}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="text-slate-200">
            <td colSpan={3} className="py-1 pr-2 text-right font-medium">
              Explained military change
            </td>
            <td className="py-1 tabular-nums font-medium">
              {formatSignedDelta(arithmetic.explainedMilitaryChange)}
            </td>
          </tr>
          <tr className="text-slate-400">
            <td colSpan={3} className="py-1 pr-2 text-right">
              Observed military change
            </td>
            <td className="py-1 tabular-nums">
              {formatSignedDelta(arithmetic.observedMilitaryChange)}
            </td>
          </tr>
        </tfoot>
      </table>
      {!arithmetic.matchesObserved ? (
        <p className="mt-2 text-xs text-amber-300/90">
          Explained military change does not match the observed scoreboard delta.
        </p>
      ) : null}
    </div>
  )
}

function SegmentConstraints({ segment }: { segment: AcceleratedInferenceSegment }) {
  return (
    <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs text-slate-300">
      <dt className="text-slate-400">Military change</dt>
      <dd className="tabular-nums">
        {formatSignedDelta(militaryChangeFromDelta2x(segment.militaryDelta2x))}
        <span className="ml-1 text-slate-500">
          (2× scale {formatSignedDelta(segment.militaryDelta2x)})
        </span>
      </dd>
      <dt className="text-slate-400">Warship change</dt>
      <dd className="tabular-nums">{formatSignedDelta(segment.warshipDelta)}</dd>
      <dt className="text-slate-400">Freighter change</dt>
      <dd className="tabular-nums">{formatSignedDelta(segment.freighterDelta)}</dd>
    </dl>
  )
}

function AcceleratedSegmentSection({
  segment,
  scoreboardTurn,
}: {
  segment: AcceleratedInferenceSegment
  scoreboardTurn: number | undefined
}) {
  return (
    <section className="rounded border border-[#52575d]/70 bg-[#2a2d30] p-3">
      <h3 className="text-xs font-medium text-slate-200">
        {acceleratedSegmentTitle(segment, scoreboardTurn)}
      </h3>
      <SegmentConstraints segment={segment} />
      {segment.solutions.length > 0 ? (
        <div className="mt-3 flex flex-col gap-3">
          {segment.solutions.map((solution, index) => (
            <SolutionSection key={`${segment.segmentId}-solution-${index}`} solution={solution} index={index} />
          ))}
        </div>
      ) : (
        <p className="mt-2 text-xs text-slate-500">No feasible build explanation found.</p>
      )}
    </section>
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
    <section
      className="rounded border border-[#52575d]/70 bg-[#2a2d30] p-3"
    >
      <h3 className="text-xs font-medium text-slate-200">Solution {index + 1}</h3>
      {arithmetic != null && arithmetic.lineItems.length > 0 ? (
        <MilitaryScoreArithmeticTable arithmetic={arithmetic} />
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

export function InferenceDetailModal({
  isOpen,
  onClose,
  racePlayer,
  detail,
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
  const acceleratedSegments = readAcceleratedInferenceSegments(diagnostics)
  const solver = readSolverSummary(diagnostics)
  const priorTurn =
    constraints?.turn != null && constraints.turn > 1 ? constraints.turn - 1 : null

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
            {constraints?.turn != null ? (
              <p className="mt-1 text-xs text-slate-400">
                {priorTurn != null ? `Turn ${priorTurn} → ${constraints.turn}` : `Turn ${constraints.turn}`}
                {constraints.playerId != null ? ` · Player ${constraints.playerId}` : ''}
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
            <h3 className="text-xs font-medium text-slate-200">
              {acceleratedSegments != null
                ? 'Scoreboard row constraints'
                : 'Observed constraints'}
            </h3>
            <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs text-slate-300">
              {constraints.militaryDelta2x != null ? (
                <>
                  <dt className="text-slate-400">Military change</dt>
                  <dd className="tabular-nums">
                    {formatSignedDelta(
                      militaryChangeFromDelta2x(constraints.militaryDelta2x)
                    )}
                    <span className="ml-1 text-slate-500">
                      (2× scale {formatSignedDelta(constraints.militaryDelta2x)})
                    </span>
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
            {constraints.appliedEqualities != null && constraints.appliedEqualities.length > 0 ? (
              <ul className="mt-2 list-inside list-disc text-xs text-slate-500">
                {constraints.appliedEqualities.map((equality) => (
                  <li key={equality}>{equality}</li>
                ))}
              </ul>
            ) : null}
          </section>
        ) : null}

        {constraints?.priorityPointConstraintNote != null ? (
          <p className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
            {constraints.priorityPointConstraintNote}
          </p>
        ) : null}

        <p className="text-xs text-slate-300">{detail.summary}</p>

        {solver.status != null || solver.wallTimeSeconds != null ? (
          <p className="text-xs text-slate-500">
            {solver.status != null ? `Solver ${solver.status}` : 'Solver'}
            {solver.wallTimeSeconds != null
              ? ` · ${solver.wallTimeSeconds.toFixed(2)}s`
              : ''}
          </p>
        ) : null}

        {acceleratedSegments != null ? (
          <div className="flex flex-col gap-3">
            <p className="text-xs text-slate-400">
              Accelerated-start game: build inference split by host turn.
            </p>
            {acceleratedSegments.map((segment) => (
              <AcceleratedSegmentSection
                key={segment.segmentId}
                segment={segment}
                scoreboardTurn={constraints?.turn}
              />
            ))}
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {detail.solutions.map((solution, index) => (
              <SolutionSection key={`solution-${index}`} solution={solution} index={index} />
            ))}
          </div>
        )}

        {!detail.isComplete ? (
          <p className="text-xs text-amber-300/90">
            Inference stopped before all alternatives were explored.
          </p>
        ) : null}
      </div>
    </div>
  )
}
