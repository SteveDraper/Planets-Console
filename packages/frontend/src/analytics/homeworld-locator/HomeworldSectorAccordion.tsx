/**
 * Per-sector collapsible sections for the homeworld locator panel / tabular tile.
 * Sector title chrome toggles region multi-select (outline visibility).
 */

import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '../../lib/utils'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { homeworldBaselineDegradedMessage } from './constants'
import { HomeworldCandidateRows } from './HomeworldCandidateRows'
import type { HomeworldSectorPanelSection } from './homeworldSectorPanelModel'
import type { HomeworldCandidateRecord } from './wireSchema'
import type { OwnershipAssertTarget } from './resolveOwnershipAssertTarget'

type HomeworldSectorAccordionSharedProps = {
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

type HomeworldSectorAccordionInteractiveProps = HomeworldSectorAccordionSharedProps & {
  mode: 'interactive'
  mutationPending?: boolean
  resolveOwnershipTarget: (row: HomeworldCandidateRecord) => OwnershipAssertTarget | null
  onAssertLocation: (planetId: number) => void
  onRevokeLocation: (planetId: number) => void
  onAssertOwnership: (target: OwnershipAssertTarget, ownerSlot: number) => void
  onRevokeOwnership: (target: OwnershipAssertTarget, ownerSlot: number) => void
}

type HomeworldSectorAccordionReadOnlyProps = HomeworldSectorAccordionSharedProps & {
  mode: 'readOnly'
}

export type HomeworldSectorAccordionProps =
  | HomeworldSectorAccordionInteractiveProps
  | HomeworldSectorAccordionReadOnlyProps

function SectorSection({
  section,
  isSelected,
  onToggleSelected,
  defaultExpanded,
  children,
  compact,
}: {
  section: HomeworldSectorPanelSection
  isSelected: boolean
  onToggleSelected: () => void
  defaultExpanded: boolean
  children: ReactNode
  compact: boolean
}) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const candidateCount = section.candidates.length
  const previousCandidateCountRef = useRef(candidateCount)

  // When planet positions arrive after overlays, candidates move from Unassigned
  // into sectors -- open the section so assert controls stay reachable.
  useEffect(() => {
    const previous = previousCandidateCountRef.current
    previousCandidateCountRef.current = candidateCount
    if (previous === 0 && candidateCount > 0) {
      setExpanded(true)
    }
  }, [candidateCount])

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

function CandidateBlock(
  props: HomeworldSectorAccordionProps & {
    rows: readonly HomeworldCandidateRecord[]
  }
) {
  const { rows, compact = false } = props
  const shared = {
    rows,
    baselineDegraded: false,
    baselineTurn: props.baselineTurn,
    roster: props.roster,
    selectedPlanetId: props.selectedPlanetId,
    onSelectPlanet: props.onSelectPlanet,
    compact,
    showHeader: !compact,
    emptyMessage: 'No candidates in this sector.',
  }

  if (props.mode === 'interactive') {
    return (
      <HomeworldCandidateRows
        {...shared}
        mode="interactive"
        mutationPending={props.mutationPending}
        resolveOwnershipTarget={props.resolveOwnershipTarget}
        onAssertLocation={props.onAssertLocation}
        onRevokeLocation={props.onRevokeLocation}
        onAssertOwnership={props.onAssertOwnership}
        onRevokeOwnership={props.onRevokeOwnership}
      />
    )
  }

  return <HomeworldCandidateRows {...shared} mode="readOnly" />
}

/**
 * Sector accordion: one collapsible section per homeworld sector, preferred-first
 * candidates, title multi-select chrome tied to region selection store.
 */
export function HomeworldSectorAccordion(props: HomeworldSectorAccordionProps) {
  const {
    sections,
    unassigned,
    baselineDegraded,
    baselineTurn,
    compact = false,
    selectedSectorIndexes,
    onToggleSectorIndex,
  } = props

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
          defaultExpanded={section.candidates.length > 0}
          compact={compact}
        >
          <CandidateBlock {...props} rows={section.candidates} />
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
          <CandidateBlock {...props} rows={unassigned} />
        </section>
      ) : null}
    </div>
  )
}
