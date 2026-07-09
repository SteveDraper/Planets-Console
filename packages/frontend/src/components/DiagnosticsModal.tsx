import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ClipboardCopy } from 'lucide-react'
import type { AnalyticShellScope } from '../api/bff'
import {
  isIncludeDiagnosticsSessionEnabled,
  setIncludeDiagnosticsSessionEnabled,
} from '../api/bff'
import { useModalKeydownFocusTrap } from '../lib/modalKeydownFocusTrap'
import { restoreFocusToElementOrFallback } from '../lib/restoreFocus'
import { cn } from '../lib/utils'
import { useAnalyticDiagnosticsStore } from '../stores/analyticDiagnostics'
import { useComputeDiagnosticsStore } from '../stores/computeDiagnostics'
import { DiagnosticsComputeTab } from './diagnostics/DiagnosticsComputeTab'
import {
  DiagnosticsRequestsTab,
  formatAllDiagnosticsItems,
  loadDiagnosticsRecentItems,
} from './diagnostics/DiagnosticsRequestsTab'
import { DiagnosticsScoresTab } from './diagnostics/DiagnosticsScoresTab'
import {
  DIAGNOSTICS_TAB_IDS,
  DIAGNOSTICS_TAB_IDS_WITHOUT_COMPUTE,
  DIAGNOSTICS_TAB_LABELS,
  type DiagnosticsTabId,
} from './diagnostics/diagnosticsTabs'

type DiagnosticsModalProps = {
  isOpen: boolean
  onClose: () => void
  analyticScope: AnalyticShellScope | null
  computeDiagnosticsEnabled: boolean
  getFocusRestoreFallback?: () => HTMLElement | null
}

export function DiagnosticsModal({
  isOpen,
  onClose,
  analyticScope,
  computeDiagnosticsEnabled,
  getFocusRestoreFallback,
}: DiagnosticsModalProps) {
  const queryClient = useQueryClient()
  const dialogRef = useRef<HTMLDivElement>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)
  const [activeTab, setActiveTab] = useState<DiagnosticsTabId>('requests')
  const [items, setItems] = useState<Awaited<
    ReturnType<typeof loadDiagnosticsRecentItems>
  > | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [clipboardError, setClipboardError] = useState<string | null>(null)
  const [recordBffDiagnostics, setRecordBffDiagnostics] = useState(false)
  const scoresSnapshot = useAnalyticDiagnosticsStore((state) => state.scores)
  const computeSnapshot = useComputeDiagnosticsStore((state) => state.snapshot)

  const visibleTabIds: readonly DiagnosticsTabId[] = computeDiagnosticsEnabled
    ? DIAGNOSTICS_TAB_IDS
    : DIAGNOSTICS_TAB_IDS_WITHOUT_COMPUTE

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
    if (!visibleTabIds.includes(activeTab)) {
      setActiveTab('requests')
    }
  }, [activeTab, isOpen, visibleTabIds])

  useEffect(() => {
    if (!isOpen) return
    setLoadError(null)
    setClipboardError(null)
    setItems(null)
    setRecordBffDiagnostics(isIncludeDiagnosticsSessionEnabled())
    let cancelled = false
    void loadDiagnosticsRecentItems()
      .then((recentItems) => {
        if (cancelled) return
        setItems(recentItems)
      })
      .catch((e: unknown) => {
        if (cancelled) return
        setLoadError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      cancelled = true
    }
  }, [isOpen])

  useModalKeydownFocusTrap(isOpen, dialogRef, closeAndReturnFocus)

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

  const copyActiveTab = () => {
    if (activeTab === 'requests') {
      if (!items?.length) return
      runClipboardCopy(formatAllDiagnosticsItems(items))
      return
    }
    if (activeTab === 'scores' && scoresSnapshot != null) {
      runClipboardCopy(JSON.stringify(scoresSnapshot, null, 2))
      return
    }
    if (activeTab === 'compute' && computeSnapshot != null) {
      runClipboardCopy(JSON.stringify(computeSnapshot, null, 2))
    }
  }

  if (!isOpen) return null

  const canCopyActiveTab =
    activeTab === 'requests'
      ? Boolean(items?.length)
      : activeTab === 'scores'
        ? scoresSnapshot != null
        : computeSnapshot != null

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
          'flex max-h-[85vh] w-[min(48rem,100vw-2rem)] flex-col overflow-hidden',
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
              onClick={copyActiveTab}
              disabled={!canCopyActiveTab}
              className={cn(
                'inline-flex items-center gap-1 rounded p-1.5 text-slate-300',
                'hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-40',
                'focus:outline-none focus:ring-1 focus:ring-slate-400'
              )}
              title="Copy active tab to clipboard"
              aria-label="Copy active tab to clipboard"
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

        <div
          className="flex gap-1 border-b border-[#52575d] px-4 pt-2"
          role="tablist"
          aria-label="Diagnostics sections"
        >
          {visibleTabIds.map((tabId) => (
            <button
              key={tabId}
              type="button"
              role="tab"
              aria-selected={activeTab === tabId}
              onClick={() => setActiveTab(tabId)}
              className={cn(
                'rounded-t px-3 py-2 text-xs font-medium',
                activeTab === tabId
                  ? 'bg-[#40454a] text-slate-100'
                  : 'text-slate-400 hover:bg-white/5 hover:text-slate-200'
              )}
            >
              {DIAGNOSTICS_TAB_LABELS[tabId]}
            </button>
          ))}
        </div>

        {activeTab === 'requests' ? (
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
                  void queryClient.invalidateQueries({ queryKey: ['bff'] })
                  void queryClient.invalidateQueries({ queryKey: ['analytic'] })
                }}
              />
              <span>
                <span className="font-medium text-slate-200">Record BFF diagnostics</span>
                <span className="mt-0.5 block text-xs text-slate-500">
                  Adds <code className="text-slate-400">includeDiagnostics=true</code> to BFF
                  calls from this tab. Toggling refetches cached BFF data so new requests include
                  timing trees in this tab.
                </span>
              </span>
            </label>
          </div>
        ) : null}

        <div className="min-h-0 flex-1 overflow-y-auto p-4" role="tabpanel">
          {clipboardError != null && (
            <p className="mb-2 text-sm text-red-400" role="alert">
              {clipboardError}
            </p>
          )}
          {activeTab === 'requests' ? (
            <DiagnosticsRequestsTab items={items} loadError={loadError} onCopy={runClipboardCopy} />
          ) : activeTab === 'scores' ? (
            <DiagnosticsScoresTab snapshot={scoresSnapshot} onCopy={runClipboardCopy} />
          ) : (
            <DiagnosticsComputeTab scope={analyticScope} onCopy={runClipboardCopy} />
          )}
        </div>
      </div>
    </div>
  )
}
