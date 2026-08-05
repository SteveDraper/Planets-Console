/**
 * Per-sector collapsible sections for the homeworld locator sidebar panel.
 * Sector title chrome toggles region multi-select (outline visibility).
 * Assert/revoke lives on the map context menu -- candidate rows are read-only.
 */

import { useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '../../lib/utils'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { homeworldBaselineDegradedMessage } from './constants'
import { HomeworldCandidateRows } from './HomeworldCandidateRows'
import type { HomeworldSectorPanelSection } from './homeworldSectorPanelModel'
import type { HomeworldCandidateRecord } from './wireSchema'

export type HomeworldSectorAccordionProps = {
  sections: readonly HomeworldSectorPanelSection[]
  unassigned: readonly HomeworldCandidateRecord[]
  baselineDegraded: boolean
  baselineTurn: number | null | undefined
  roster: readonly PerspectiveRow[]
  selectedPlanetId: number | null
  onSelectPlanet: (planetId: number) => void
  selectedSectorIndexes: ReadonlySet<number>
  onToggleSectorIndex: (sectorIndex: number) => void
  /** Compact layout for the narrow sidebar panel. */
  compact?: boolean
}

function SectorSection({
  section,
  isSelected,
  onToggleSelected,
  children,
  compact,
}: {
  section: HomeworldSectorPanelSection
  isSelected: boolean
  onToggleSelected: () => void
  children: ReactNode
  compact: boolean
}) {
  // Session start: all player sectors collapsed; user expands explicitly.
  const [expanded, setExpanded] = useState(false)

  return (
    <section
      className={cn(
        'rounded bg-slate-900/40',
        isSelected ? 'border-2 border-sky-400/80' : 'border border-[#52575d]',
        compact ? 'px-1 py-0.5' : 'px-2 py-1'
      )}
      data-sector-index={section.sectorIndex}
      data-selected={isSelected ? 'true' : 'false'}
    >
      <div className="flex min-w-0 items-center gap-0.5">
        <button
          type="button"
          title={section.titleHover ?? undefined}
          aria-pressed={isSelected}
          aria-label={`Toggle sector selection: ${section.title}`}
          className={cn(
            'min-w-0 flex-1 truncate text-left font-medium text-slate-200 hover:text-white',
            compact ? 'px-0.5 py-0.5 text-[11px]' : 'px-1 py-1 text-sm'
          )}
          onClick={onToggleSelected}
        >
          {section.title}
        </button>
        <button
          type="button"
          aria-expanded={expanded}
          aria-label={
            expanded
              ? `Collapse sector ${section.title}`
              : `Expand sector ${section.title}`
          }
          className={cn(
            'flex shrink-0 items-center justify-center rounded text-slate-400 hover:bg-black/20 hover:text-slate-200',
            compact ? 'h-6 w-6' : 'h-7 w-7'
          )}
          onClick={() => setExpanded((value) => !value)}
        >
          <ChevronDown
            className={cn(
              'h-3.5 w-3.5 shrink-0 transition-transform duration-150',
              !expanded && '-rotate-90'
            )}
            aria-hidden
          />
        </button>
      </div>
      {expanded ? <div className={compact ? 'pt-0.5' : 'pt-1'}>{children}</div> : null}
    </section>
  )
}

/**
 * Sector accordion: one collapsible section per homeworld sector, preferred-first
 * candidates, title multi-select chrome tied to region selection store.
 */
export function HomeworldSectorAccordion({
  sections,
  unassigned,
  baselineDegraded,
  baselineTurn,
  roster,
  selectedPlanetId,
  onSelectPlanet,
  selectedSectorIndexes,
  onToggleSectorIndex,
  compact = false,
}: HomeworldSectorAccordionProps) {
  const candidateRowsProps = {
    baselineDegraded: false as const,
    baselineTurn,
    roster,
    selectedPlanetId,
    onSelectPlanet,
    compact,
    showHeader: !compact,
    emptyMessage: 'No candidates in this sector.',
  }

  return (
    <div className={cn('flex flex-col', compact ? 'gap-1' : 'gap-2')}>
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
      {sections.map((section) => (
        <SectorSection
          key={section.sectorIndex}
          section={section}
          isSelected={selectedSectorIndexes.has(section.sectorIndex)}
          onToggleSelected={() => onToggleSectorIndex(section.sectorIndex)}
          compact={compact}
        >
          <HomeworldCandidateRows
            {...candidateRowsProps}
            rows={section.candidates}
            showOwnerColumn={false}
            possibleOwners={section.overlay.possibleOwners}
            ownershipWinningStrength={section.overlay.ownershipWinningStrength}
          />
        </SectorSection>
      ))}
      {unassigned.length > 0 ? (
        <section
          className={cn(
            'rounded border border-dashed border-[#52575d] bg-slate-900/20',
            compact ? 'px-1 py-0.5' : 'px-2 py-1'
          )}
        >
          <div
            className={cn(
              'font-medium text-slate-400',
              compact ? 'px-0.5 py-0.5 text-[11px]' : 'px-1 py-1 text-sm'
            )}
          >
            Unassigned
          </div>
          <HomeworldCandidateRows {...candidateRowsProps} rows={unassigned} />
        </section>
      ) : null}
    </div>
  )
}
