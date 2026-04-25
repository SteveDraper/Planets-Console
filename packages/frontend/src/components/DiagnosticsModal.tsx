import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ClipboardCopy } from 'lucide-react'
import {
  fetchDiagnosticsRecent,
  isIncludeDiagnosticsSessionEnabled,
  setIncludeDiagnosticsSessionEnabled,
  type DiagnosticsRecentItem,
} from '../api/bff'
import { restoreFocusToElementOrFallback } from '../lib/restoreFocus'
import { cn } from '../lib/utils'

type DiagnosticsModalProps = {
  isOpen: boolean
  onClose: () => void
  getFocusRestoreFallback?: () => HTMLElement | null
}

function formatBlob(item: DiagnosticsRecentItem): string {
  return JSON.stringify(
    { capturedAt: item.capturedAt, summary: item.summary, diagnostics: item.diagnostics },
    null,
    2
  )
}

export function DiagnosticsModal({
  isOpen,
  onClose,
  getFocusRestoreFallback,
}: DiagnosticsModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)
  const [items, setItems] = useState<DiagnosticsRecentItem[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [clipboardError, setClipboardError] = useState<string | null>(null)
  const [recordBffDiagnostics, setRecordBffDiagnostics] = useState(false)

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
    for (const node of focusables) {
      if (node.matches(':disabled')) {
        continue
      }
      node.focus()
      return
    }
    el.focus()
  }, [isOpen])

  useEffect(() => {
    if (!isOpen) return
    setLoadError(null)
    setClipboardError(null)
    setItems(null)
    setRecordBffDiagnostics(isIncludeDiagnosticsSessionEnabled())
    void fetchDiagnosticsRecent()
      .then((r) => setItems(r.items))
      .catch((e: unknown) => {
        setLoadError(e instanceof Error ? e.message : String(e))
      })
  }, [isOpen])

  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        closeAndReturnFocus()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, closeAndReturnFocus])

  const runClipboardCopy = useCallback((text: string) => {
    if (typeof globalThis.isSecureContext === 'boolean' && !globalThis.isSecureContext) {
      setClipboardError(
        'Clipboard needs a secure context (HTTPS). Open the app over HTTPS or use localhost.'
      )
      return
    }
    if (
      typeof navigator === 'undefined' ||
      typeof navigator.clipboard?.writeText !== 'function'
    ) {
      setClipboardError(
        'Clipboard API is not available in this browser or context. Check permissions or try another browser.'
      )
      return
    }
    void navigator.clipboard
      .writeText(text)
      .then(() => {
        setClipboardError(null)
      })
      .catch((e: unknown) => {
        const msg =
          e instanceof Error
            ? e.message
            : typeof e === 'string'
              ? e
              : 'Could not copy to clipboard.'
        setClipboardError(msg || 'Could not copy to clipboard.')
      })
  }, [])

  const copyOne = (item: DiagnosticsRecentItem) => {
    runClipboardCopy(formatBlob(item))
  }

  const copyAll = () => {
    if (!items?.length) return
    runClipboardCopy(
      JSON.stringify(
        {
          items: items.map((i) => ({
            capturedAt: i.capturedAt,
            summary: i.summary,
            diagnostics: i.diagnostics,
          })),
        },
        null,
        2
      )
    )
  }

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      role="presentation"
      onMouseDown={(e) => e.target === e.currentTarget && closeAndReturnFocus()}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="diagnostics-title"
        tabIndex={-1}
        className={cn(
          'flex max-h-[85vh] w-[min(42rem,100vw-2rem)] flex-col overflow-hidden',
          'rounded-lg border border-[#52575d] bg-[#2d3136] shadow-xl',
          'outline-none focus-visible:ring-1 focus-visible:ring-slate-400'
        )}
      >
        <div className="flex items-center justify-between border-b border-[#52575d] px-4 py-3">
          <h2 id="diagnostics-title" className="text-sm font-medium text-slate-100">
            Diagnostics
          </h2>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={copyAll}
              disabled={!items?.length}
              className={cn(
                'inline-flex items-center gap-1 rounded p-1.5 text-slate-300',
                'hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-40',
                'focus:outline-none focus:ring-1 focus:ring-slate-400'
              )}
              title="Copy all to clipboard"
              aria-label="Copy all diagnostics to clipboard"
            >
              <ClipboardCopy className="h-4 w-4" aria-hidden />
            </button>
            <button
              type="button"
              onClick={closeAndReturnFocus}
              className="rounded px-2 py-1 text-xs text-slate-300 hover:bg-white/10"
            >
              Close
            </button>
          </div>
        </div>
        <div className="border-b border-[#52575d] px-4 py-2">
          <label className="flex cursor-pointer select-none items-start gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              className="mt-0.5 h-3.5 w-3.5 rounded border border-[#52575d] bg-[#2d3136] accent-slate-400"
              checked={recordBffDiagnostics}
              onChange={(e) => {
                const on = e.target.checked
                setIncludeDiagnosticsSessionEnabled(on)
                setRecordBffDiagnostics(on)
              }}
            />
            <span>
              <span className="font-medium text-slate-200">Record BFF diagnostics</span>
              <span className="mt-0.5 block text-xs text-slate-500">
                Adds <code className="text-slate-400">includeDiagnostics=true</code> to BFF
                calls from this tab (maps, games, shell, etc.). Then trigger a request — e.g.
                change a map control or refresh data — and open this panel again; recent trees
                appear in the buffer below. Cleared when the tab ends.
              </span>
            </span>
          </label>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {clipboardError != null && (
            <p className="mb-2 text-sm text-red-400" role="alert">
              {clipboardError}
            </p>
          )}
          {loadError != null && (
            <p className="text-sm text-red-400" role="alert">
              {loadError}
            </p>
          )}
          {loadError == null && items == null && (
            <p className="text-sm text-slate-400">Loading…</p>
          )}
          {loadError == null && items != null && items.length === 0 && (
            <p className="text-sm text-slate-400">
              No entries yet. Turn on <span className="font-medium text-slate-300">Record BFF diagnostics</span> above, then
              trigger a BFF request in the console (or add{' '}
              <code className="text-slate-300">includeDiagnostics=true</code> to a BFF URL yourself).
            </p>
          )}
          {items != null && items.length > 0 && (
            <ul className="flex flex-col gap-3">
              {items.map((item) => {
                const label = item.summary || item.capturedAt
                return (
                  <li
                    key={`${item.capturedAt}-${item.summary}`}
                    className="rounded border border-[#52575d] bg-[#40454a] p-2"
                  >
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <span
                        className="min-w-0 flex-1 truncate text-xs text-slate-200"
                        title={label}
                      >
                        {label}
                      </span>
                      <button
                        type="button"
                        onClick={() => copyOne(item)}
                        className={cn(
                          'shrink-0 inline-flex items-center gap-1 rounded p-1 text-slate-300',
                          'hover:bg-white/10 focus:outline-none focus:ring-1 focus:ring-slate-400'
                        )}
                        title="Copy this entry"
                        aria-label="Copy to clipboard"
                      >
                        <ClipboardCopy className="h-3.5 w-3.5" aria-hidden />
                      </button>
                    </div>
                    <pre className="max-h-40 overflow-auto text-[10px] leading-snug text-slate-400 break-all whitespace-pre-wrap">
                      {formatBlob(item)}
                    </pre>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
