/**
 * Shared candidate row list for the homeworld locator sidebar panel.
 * Assert/revoke lives on the map context menu -- rows are read-only.
 */

import { cn } from '../../lib/utils'
import type {
  MapRegionPossibleOwner,
  OwnershipWinningStrength,
} from '../../api/mapRegionOverlayTypes'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { homeworldBaselineDegradedMessage } from './constants'
import {
  formatHomeworldCandidateConfidenceLabel,
  formatHomeworldCandidateOwnerSlotLabel,
} from './formatHomeworldCandidateLabels'
import { formatHomeworldPlanetHover } from './formatHomeworldPlanetHover'
import type { HomeworldCandidateRecord } from './wireSchema'

export type HomeworldCandidateRowsProps = {
  rows: readonly HomeworldCandidateRecord[]
  baselineDegraded: boolean
  baselineTurn: number | null | undefined
  roster: readonly PerspectiveRow[]
  onSelectPlanet: (planetId: number) => void
  /** Compact layout for the narrow sidebar panel. */
  compact?: boolean
  /** When false, omit the column header row (used inside sector sections). */
  showHeader?: boolean
  /**
   * Owner column. Default true for Unassigned lists.
   * False inside sector/player sections -- section title already carries ownership.
   */
  showOwnerColumn?: boolean
  /** Override empty-state copy (sector sections use a quieter message). */
  emptyMessage?: string
  /**
   * Sector (or planet-keyed) ownership evidence for expanding planet-row hover
   * ``inferred`` with observation counts.
   */
  possibleOwners?: readonly MapRegionPossibleOwner[]
  /** Overlay winning ownership strength after overlay projection. */
  ownershipWinningStrength?: OwnershipWinningStrength | null
}

/** Candidate table for the homeworld locator sidebar panel (read-only). */
export function HomeworldCandidateRows({
  rows,
  baselineDegraded,
  baselineTurn,
  roster,
  onSelectPlanet,
  compact = false,
  showHeader = true,
  showOwnerColumn = true,
  emptyMessage = 'No homeworld candidates inferred.',
  possibleOwners,
  ownershipWinningStrength,
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
          {emptyMessage}
        </div>
      ) : (
        <div className="overflow-auto">
          <table className={cn('min-w-full border-collapse', textSize)}>
            {showHeader ? (
              <thead>
                <tr className="border-b border-[#52575d]">
                  <th className={cn(cellPad, 'text-left font-medium text-slate-200')}>Planet</th>
                  {showOwnerColumn ? (
                    <th className={cn(cellPad, 'text-left font-medium text-slate-200')}>Owner</th>
                  ) : null}
                  <th className={cn(cellPad, 'text-left font-medium text-slate-200')}>
                    Confidence
                  </th>
                </tr>
              </thead>
            ) : null}
            <tbody>
              {rows.map((row) => (
                  <tr
                    key={`${row.planetId}-${row.perspective ?? 'orphan'}-${row.confidenceTier}`}
                    className={cn(
                      'border-b border-[#52575d]/60',
                      'cursor-pointer'
                    )}
                    title={formatHomeworldPlanetHover(row, roster, {
                      possibleOwners,
                      ownershipWinningStrength,
                    })}
                    onClick={() => onSelectPlanet(row.planetId)}
                  >
                    <td className={cn(cellPad, 'text-slate-200 tabular-nums')}>{row.planetId}</td>
                    {showOwnerColumn ? (
                      <td className={cn(cellPad, 'text-slate-300')}>
                        {formatHomeworldCandidateOwnerSlotLabel(row.perspective, roster)}
                      </td>
                    ) : null}
                    <td className={cn(cellPad, 'text-slate-300')}>
                      {formatHomeworldCandidateConfidenceLabel(row, { includeAsserted: true })}
                    </td>
                  </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
