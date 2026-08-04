/**
 * Shared candidate row list for homeworld locator panel (interactive) and
 * tabular tile (read-only mirror).
 */

import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { cn } from '../../lib/utils'
import {
  CONFIDENCE_DEFINITE,
  homeworldBaselineDegradedMessage,
} from './constants'
import { formatHomeworldOwnershipPickLabel } from './ownershipPickLabel'
import type { HomeworldCandidateRecord } from './wireSchema'
import type { OwnershipAssertTarget } from './resolveOwnershipAssertTarget'

export type HomeworldCandidateRowsMode = 'interactive' | 'readOnly'

export type HomeworldCandidateRowsProps = {
  rows: readonly HomeworldCandidateRecord[]
  baselineDegraded: boolean
  baselineTurn: number | null | undefined
  mode: HomeworldCandidateRowsMode
  roster: readonly PerspectiveRow[]
  selectedPlanetId: number | null
  onSelectPlanet: (planetId: number) => void
  /** Compact layout for the narrow sidebar panel. */
  compact?: boolean
  mutationPending?: boolean
  resolveOwnershipTarget?: (row: HomeworldCandidateRecord) => OwnershipAssertTarget | null
  onAssertLocation?: (planetId: number) => void
  onRevokeLocation?: (planetId: number) => void
  onAssertOwnership?: (target: OwnershipAssertTarget, ownerSlot: number) => void
  onRevokeOwnership?: (target: OwnershipAssertTarget, ownerSlot: number) => void
}

function confidenceLabel(row: HomeworldCandidateRecord): string {
  if (row.confidenceTier === CONFIDENCE_DEFINITE) return 'Definite'
  if (row.isMostProbable) return 'Possible (most probable)'
  return 'Possible'
}

function slotLabel(perspective: number | null, roster: readonly PerspectiveRow[]): string {
  if (perspective == null) return 'Orphan'
  const player = roster.find((row) => row.ordinal === perspective)
  if (player != null) {
    return formatHomeworldOwnershipPickLabel(player.name, player.raceName)
  }
  return `Slot ${perspective}`
}

/**
 * Candidate table shared by sidebar panel and main-area tabular tile.
 */
export function HomeworldCandidateRows({
  rows,
  baselineDegraded,
  baselineTurn,
  mode,
  roster,
  selectedPlanetId,
  onSelectPlanet,
  compact = false,
  mutationPending = false,
  resolveOwnershipTarget,
  onAssertLocation,
  onRevokeLocation,
  onAssertOwnership,
  onRevokeOwnership,
}: HomeworldCandidateRowsProps) {
  const cellPad = compact ? 'px-1.5 py-1' : 'px-3 py-2'
  const textSize = compact ? 'text-[11px]' : 'text-sm'

  return (
    <div className={cn('flex flex-col gap-2', compact ? 'gap-1.5' : 'p-2')}>
      {baselineDegraded ? (
        <p
          className={cn(
            'text-amber-300/90',
            compact ? 'px-0.5 text-[10px] leading-snug' : 'px-2 text-xs'
          )}
          role="status"
        >
          {homeworldBaselineDegradedMessage(baselineTurn)}
        </p>
      ) : null}
      {rows.length === 0 ? (
        <div
          className={cn(
            'text-slate-400',
            compact ? 'px-0.5 py-1 text-[11px]' : 'px-2 py-2 text-sm'
          )}
        >
          No homeworld candidates inferred.
        </div>
      ) : (
        <div className="overflow-auto">
          <table className={cn('min-w-full border-collapse', textSize)}>
            <thead>
              <tr className="border-b border-[#52575d]">
                <th className={cn(cellPad, 'text-left font-medium text-slate-200')}>Planet</th>
                <th className={cn(cellPad, 'text-left font-medium text-slate-200')}>Owner</th>
                <th className={cn(cellPad, 'text-left font-medium text-slate-200')}>
                  Confidence
                </th>
                {!compact ? (
                  <th className={cn(cellPad, 'text-left font-medium text-slate-200')}>
                    Attribution
                  </th>
                ) : null}
                <th className={cn(cellPad, 'text-left font-medium text-slate-200')}>Asserted</th>
                {mode === 'interactive' ? (
                  <th className={cn(cellPad, 'text-left font-medium text-slate-200')}>Actions</th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const selected = selectedPlanetId === row.planetId
                const ownershipTarget = resolveOwnershipTarget?.(row) ?? null
                return (
                  <tr
                    key={`${row.planetId}-${row.perspective ?? 'orphan'}-${row.confidenceTier}`}
                    className={cn(
                      'border-b border-[#52575d]/60',
                      selected && 'bg-sky-500/15',
                      'cursor-pointer'
                    )}
                    onClick={() => onSelectPlanet(row.planetId)}
                    aria-selected={selected}
                  >
                    <td className={cn(cellPad, 'text-slate-200 tabular-nums')}>{row.planetId}</td>
                    <td className={cn(cellPad, 'text-slate-300')}>
                      {slotLabel(row.perspective, roster)}
                    </td>
                    <td className={cn(cellPad, 'text-slate-300')}>{confidenceLabel(row)}</td>
                    {!compact ? (
                      <td className={cn(cellPad, 'text-slate-400')}>{row.attribution}</td>
                    ) : null}
                    <td className={cn(cellPad, 'text-slate-300')}>
                      {row.assertedCue === true ? 'Yes' : '—'}
                    </td>
                    {mode === 'interactive' ? (
                      <td
                        className={cn(cellPad, 'text-slate-300')}
                        onClick={(event) => event.stopPropagation()}
                      >
                        <div className="flex min-w-[9rem] flex-col gap-1">
                          <div className="flex flex-wrap gap-1">
                            <button
                              type="button"
                              className="rounded border border-[#52575d] px-1.5 py-0.5 text-[10px] text-slate-200 hover:bg-black/20 disabled:opacity-40"
                              disabled={mutationPending}
                              onClick={() => onAssertLocation?.(row.planetId)}
                            >
                              Assert HW
                            </button>
                            <button
                              type="button"
                              className="rounded border border-[#52575d] px-1.5 py-0.5 text-[10px] text-slate-200 hover:bg-black/20 disabled:opacity-40"
                              disabled={mutationPending}
                              onClick={() => onRevokeLocation?.(row.planetId)}
                            >
                              Revoke HW
                            </button>
                          </div>
                          {ownershipTarget != null && roster.length > 0 ? (
                            <label className="flex flex-col gap-0.5 text-[10px] text-slate-400">
                              <span>Owner</span>
                              <select
                                className="max-w-full rounded border border-[#52575d] bg-slate-800 px-1 py-0.5 text-[10px] text-slate-200"
                                defaultValue=""
                                disabled={mutationPending}
                                aria-label={`Assert ownership for planet ${row.planetId}`}
                                onChange={(event) => {
                                  const value = event.target.value
                                  if (value === '') return
                                  const ownerSlot = Number.parseInt(value, 10)
                                  if (!Number.isFinite(ownerSlot)) return
                                  onAssertOwnership?.(ownershipTarget, ownerSlot)
                                  event.target.value = ''
                                }}
                              >
                                <option value="">Assert owner…</option>
                                {roster.map((player) => (
                                  <option key={player.playerId} value={player.ordinal}>
                                    {formatHomeworldOwnershipPickLabel(
                                      player.name,
                                      player.raceName
                                    )}
                                  </option>
                                ))}
                              </select>
                              {row.perspective != null ? (
                                <button
                                  type="button"
                                  className="self-start rounded border border-[#52575d] px-1.5 py-0.5 text-[10px] text-slate-200 hover:bg-black/20 disabled:opacity-40"
                                  disabled={mutationPending}
                                  onClick={() =>
                                    onRevokeOwnership?.(ownershipTarget, row.perspective!)
                                  }
                                >
                                  Revoke owner
                                </button>
                              ) : null}
                            </label>
                          ) : null}
                        </div>
                      </td>
                    ) : null}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
