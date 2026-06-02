import { useCallback, useLayoutEffect, useRef } from 'react'
import type { ScoresInferenceRowDetail } from '../../api/bff'
import { useModalKeydownFocusTrap } from '../../lib/modalKeydownFocusTrap'
import { restoreFocusToElementOrFallback } from '../../lib/restoreFocus'
import { cn } from '../../lib/utils'

type InferenceDetailModalProps = {
  isOpen: boolean
  onClose: () => void
  racePlayer: string
  detail: ScoresInferenceRowDetail | null
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
          </div>
          <button
            type="button"
            onClick={closeAndReturnFocus}
            className="rounded px-2 py-1 text-xs text-slate-400 hover:bg-white/10 hover:text-slate-200"
          >
            Close
          </button>
        </div>
        <p className="text-xs text-slate-300">{detail.summary}</p>
        <div className="flex flex-col gap-3">
          {detail.solutions.map((solution, index) => (
            <section
              key={`${solution.objectiveValue}-${index}`}
              className="rounded border border-[#52575d]/70 bg-[#2a2d30] p-3"
            >
              <h3 className="text-xs font-medium text-slate-200">
                Solution {index + 1}
                {solution.objectiveValue !== 0 ? (
                  <span className="ml-2 font-normal text-slate-400">
                    score {solution.objectiveValue}
                  </span>
                ) : null}
              </h3>
              <ul className="mt-2 flex flex-col gap-1 text-xs text-slate-300">
                {solution.actions.map((action) => (
                  <li key={action.actionId}>
                    {action.count > 1 ? `${action.count}x ` : ''}
                    {action.label}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
        {!detail.isComplete ? (
          <p className="text-xs text-amber-300/90">
            Inference stopped before all alternatives were explored.
          </p>
        ) : null}
      </div>
    </div>
  )
}
