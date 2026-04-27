import { useCallback, useLayoutEffect, useRef } from 'react'
import { useModalKeydownFocusTrap } from '../lib/modalKeydownFocusTrap'
import { restoreFocusToElementOrFallback } from '../lib/restoreFocus'
import { getAppVersionDisplayString } from '../lib/appVersion'
import { cn } from '../lib/utils'

type AboutModalProps = {
  isOpen: boolean
  onClose: () => void
  /** When the opener (e.g. a menu item) unmounts before close, focus moves here instead. */
  getFocusRestoreFallback?: () => HTMLElement | null
}

export function AboutModal({
  isOpen,
  onClose,
  getFocusRestoreFallback,
}: AboutModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)

  const closeAndReturnFocus = useCallback(() => {
    const target = returnFocusRef.current
    onClose()
    restoreFocusToElementOrFallback(target, getFocusRestoreFallback)
  }, [onClose, getFocusRestoreFallback])

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

  if (!isOpen) return null

  const versionDisplay = getAppVersionDisplayString()

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
        aria-labelledby="about-dialog-title"
        onClick={(e) => e.stopPropagation()}
        className={cn(
          'flex max-h-[min(90vh,36rem)] w-full max-w-lg flex-col gap-3 overflow-y-auto',
          'rounded border border-[#52575d] bg-[#40454a] p-4 shadow-lg',
          'focus:outline-none'
        )}
      >
        <div className="flex items-start justify-between gap-2">
          <h2 id="about-dialog-title" className="text-sm font-medium text-slate-200">
            About
          </h2>
          <button
            type="button"
            onClick={closeAndReturnFocus}
            className="rounded px-2 py-1 text-xs text-slate-400 hover:bg-white/10 hover:text-slate-200"
          >
            Close
          </button>
        </div>
        <div className="flex flex-col gap-3 text-xs text-slate-300">
          <div>
            <p className="text-sm font-medium text-slate-200">Planets Analytic Console</p>
            <p className="mt-1 text-slate-400">
              <span className="text-slate-400">Author:</span>{' '}
              <span className="text-slate-200">Steve Draper</span>
            </p>
            <p className="mt-1 text-slate-400">
              <span className="text-slate-400">Version:</span>{' '}
              <span className="tabular-nums text-slate-200">{versionDisplay}</span>
            </p>
          </div>
          <div>
            <h3 className="text-xs font-medium text-slate-200">Inspired by</h3>
            <ul className="mt-1 list-disc pl-5 text-slate-300">
              <li>Psydev&apos;s many spreadsheets</li>
              <li>McNimble&apos;s many useful plugins</li>
            </ul>
          </div>
          <div>
            <h3 className="text-xs font-medium text-slate-200">Acknowledgments and Thanks</h3>
            <ul className="mt-1 list-disc pl-5 text-slate-300">
              <li>McNimble</li>
              <li>Stefan Reuther</li>
              <li>Psydev</li>
              <li>KJN</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  )
}
