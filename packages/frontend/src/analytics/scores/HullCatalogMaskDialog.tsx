import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { AnalyticShellScope, InferenceHullCatalogMaskResponse } from '../../api/bff'
import {
  fetchInferenceHullCatalogMask,
  putInferenceHullCatalogMask,
  resetInferenceHullCatalogMask,
} from '../../api/bff'
import { useModalKeydownFocusTrap } from '../../lib/modalKeydownFocusTrap'
import { restoreFocusToElementOrFallback } from '../../lib/restoreFocus'
import { errorDetailFromUnknown } from '../../lib/queryRetry'
import { cn } from '../../lib/utils'

type HullCatalogMaskDialogProps = {
  isOpen: boolean
  onClose: () => void
  scope: AnalyticShellScope
  playerId: number
  racePlayer: string
  onSaved: () => void
}

function enabledHullIdsFromCatalog(
  catalog: InferenceHullCatalogMaskResponse['masterCatalog']
): number[] {
  return catalog.filter((entry) => entry.userEnabled).map((entry) => entry.hullId)
}

export function HullCatalogMaskDialog({
  isOpen,
  onClose,
  scope,
  playerId,
  racePlayer,
  onSaved,
}: HullCatalogMaskDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const openerRef = useRef<HTMLElement | null>(null)
  const [payload, setPayload] = useState<InferenceHullCatalogMaskResponse | null>(null)
  const [draftEnabled, setDraftEnabled] = useState<Set<number>>(new Set())
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useLayoutEffect(() => {
    if (!isOpen) {
      return
    }
    openerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
  }, [isOpen])

  const handleClose = useCallback(() => {
    onClose()
    restoreFocusToElementOrFallback(
      openerRef.current,
      () => document.querySelector<HTMLElement>('[data-hull-catalog-opener]'),
    )
  }, [onClose])

  useModalKeydownFocusTrap(isOpen, dialogRef, handleClose)

  useEffect(() => {
    if (!isOpen) {
      setPayload(null)
      setDraftEnabled(new Set())
      setError(null)
      return
    }

    let cancelled = false
    setLoading(true)
    setError(null)
    void fetchInferenceHullCatalogMask(scope, playerId)
      .then((response) => {
        if (cancelled) {
          return
        }
        setPayload(response)
        setDraftEnabled(new Set(enabledHullIdsFromCatalog(response.masterCatalog)))
      })
      .catch((fetchError) => {
        if (cancelled) {
          return
        }
        setError(errorDetailFromUnknown(fetchError))
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [isOpen, scope, playerId])

  const toggleHull = (hullId: number) => {
    setDraftEnabled((previous) => {
      const next = new Set(previous)
      if (next.has(hullId)) {
        next.delete(hullId)
      } else {
        next.add(hullId)
      }
      return next
    })
  }

  const handleReset = async () => {
    setSaving(true)
    setError(null)
    try {
      const response = await resetInferenceHullCatalogMask(scope, playerId)
      setPayload(response)
      setDraftEnabled(new Set(enabledHullIdsFromCatalog(response.masterCatalog)))
    } catch (resetError) {
      setError(errorDetailFromUnknown(resetError))
    } finally {
      setSaving(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    try {
      const response = await putInferenceHullCatalogMask(scope, playerId, [...draftEnabled].sort())
      setPayload(response)
      setDraftEnabled(new Set(enabledHullIdsFromCatalog(response.masterCatalog)))
      onSaved()
      handleClose()
    } catch (saveError) {
      setError(errorDetailFromUnknown(saveError))
    } finally {
      setSaving(false)
    }
  }

  if (!isOpen) {
    return null
  }

  const campaignLabel = payload?.campaignMode ? 'Campaign' : 'Standard'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          handleClose()
        }
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="hull-catalog-mask-title"
        className="flex max-h-[85vh] w-full max-w-lg flex-col rounded border border-[#52575d] bg-[#1e2226] shadow-xl"
      >
        <div className="border-b border-[#52575d]/80 px-4 py-3">
          <h2 id="hull-catalog-mask-title" className="text-sm font-medium text-slate-100">
            Buildable hull catalog
          </h2>
          <p className="mt-1 text-xs text-slate-400">
            {racePlayer} · {campaignLabel}
            {payload?.raceName != null ? ` · ${payload.raceName}` : ''}
          </p>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
          {loading ? (
            <p className="text-sm text-slate-400">Loading hull catalog…</p>
          ) : error != null ? (
            <p className="text-sm text-red-400">{error}</p>
          ) : payload == null ? (
            <p className="text-sm text-slate-400">No catalog data.</p>
          ) : (
            <ul className="space-y-1">
              {payload.masterCatalog.map((entry) => {
                const checked = draftEnabled.has(entry.hullId)
                const differsFromDefault = entry.defaultEnabled !== checked
                return (
                  <li key={entry.hullId}>
                    <label
                      className={cn(
                        'flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-white/5',
                        differsFromDefault ? 'text-amber-200' : 'text-slate-300'
                      )}
                    >
                      <input
                        type="checkbox"
                        className="rounded border-[#52575d]"
                        checked={checked}
                        onChange={() => toggleHull(entry.hullId)}
                        disabled={saving}
                      />
                      <span className="tabular-nums text-slate-500">{entry.hullId}</span>
                      <span>{entry.name}</span>
                      {entry.defaultEnabled ? (
                        <span className="ml-auto text-xs text-slate-500">default</span>
                      ) : null}
                    </label>
                  </li>
                )
              })}
            </ul>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-[#52575d]/80 px-4 py-3">
          <button
            type="button"
            className="rounded border border-[#52575d] px-3 py-1.5 text-xs text-slate-300 hover:bg-white/5 disabled:opacity-50"
            onClick={() => void handleReset()}
            disabled={loading || saving || payload == null}
          >
            Reset to defaults
          </button>
          <div className="flex gap-2">
            <button
              type="button"
              className="rounded border border-[#52575d] px-3 py-1.5 text-xs text-slate-300 hover:bg-white/5"
              onClick={handleClose}
              disabled={saving}
            >
              Cancel
            </button>
            <button
              type="button"
              className="rounded border border-emerald-600/70 bg-emerald-900/30 px-3 py-1.5 text-xs text-emerald-300 hover:bg-emerald-900/50 disabled:opacity-50"
              onClick={() => void handleSave()}
              disabled={loading || saving || payload == null}
            >
              Save
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
