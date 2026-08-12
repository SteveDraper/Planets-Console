/**
 * Collapsible sections for the homeworld locator sidebar panel.
 * Sector mode: title chrome toggles region multi-select (outline visibility).
 * Player mode: one section per roster player; no region-selection chrome.
 * Assert/revoke lives on the map context menu -- candidate rows are read-only.
 */

import { useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '../../lib/utils'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { homeworldBaselineDegradedMessage } from './constants'
import { HomeworldCandidateRows } from './HomeworldCandidateRows'
import type {
  HomeworldPlayerPanelSection,
  HomeworldSectorPanelSection,
} from './homeworldLocatorPanelModel'
import type { HomeworldCandidateRecord } from './wireSchema'

type AccordionCommonProps = {
  baselineDegraded: boolean
  baselineTurn: number | null | undefined
  roster: readonly PerspectiveRow[]
  onSelectPlanet: (planetId: number) => void
  /** Compact layout for the narrow sidebar panel. */
  compact?: boolean
}

export type HomeworldSectorAccordionProps = AccordionCommonProps & {
  sections: readonly HomeworldSectorPanelSection[]
  unassigned: readonly HomeworldCandidateRecord[]
  selectedSectorIndexes: ReadonlySet<number>
  onToggleSectorIndex: (sectorIndex: number) => void
}

export type HomeworldPlayerAccordionProps = AccordionCommonProps & {
  sections: readonly HomeworldPlayerPanelSection[]
}

function CollapsibleSection({
  title,
  titleHover,
  titleControl,
  children,
  compact,
  borderClassName,
  dataAttrs,
  expandLabelNoun,
}: {
  title: string
  titleHover?: string | null
  /** When set, replaces the plain title label (e.g. sector selection toggle). */
  titleControl?: ReactNode
  children: ReactNode
  compact: boolean
  borderClassName: string
  dataAttrs?: Record<string, string>
  /** Noun for expand/collapse aria labels (e.g. ``sector``, ``player``). */
  expandLabelNoun: string
}) {
  // Session start: all sections collapsed; user expands explicitly.
  const [expanded, setExpanded] = useState(false)

  return (
    <section
      className={cn(
        'rounded bg-slate-900/40',
        borderClassName,
        compact ? 'px-1 py-0.5' : 'px-2 py-1'
      )}
      {...dataAttrs}
    >
      <div className="flex min-w-0 items-center gap-0.5">
        {titleControl ?? (
          <span
            title={titleHover ?? undefined}
            className={cn(
              'min-w-0 flex-1 truncate text-left font-medium text-slate-200',
              compact ? 'px-0.5 py-0.5 text-[11px]' : 'px-1 py-1 text-sm'
            )}
          >
            {title}
          </span>
        )}
        <button
          type="button"
          aria-expanded={expanded}
          aria-label={
            expanded
              ? `Collapse ${expandLabelNoun} ${title}`
              : `Expand ${expandLabelNoun} ${title}`
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

function BaselineBanner({
  baselineDegraded,
  baselineTurn,
  compact,
}: {
  baselineDegraded: boolean
  baselineTurn: number | null | undefined
  compact: boolean
}) {
  if (!baselineDegraded) return null
  return (
    <p
      className={cn(
        'text-amber-300/90',
        compact ? 'px-0.5 text-[10px] leading-snug' : 'px-2 text-xs'
      )}
      role="status"
    >
      {homeworldBaselineDegradedMessage(baselineTurn)}
    </p>
  )
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
    roster,
    onSelectPlanet,
    selectedSectorIndexes,
    onToggleSectorIndex,
    compact = false,
  } = props

  const candidateRowsProps = {
    baselineDegraded: false as const,
    baselineTurn,
    roster,
    onSelectPlanet,
    compact,
    showHeader: !compact,
    emptyMessage: 'No candidates in this sector.',
  }

  return (
    <div className={cn('flex flex-col', compact ? 'gap-1' : 'gap-2')}>
      <BaselineBanner
        baselineDegraded={baselineDegraded}
        baselineTurn={baselineTurn}
        compact={compact}
      />
      {sections.map((section) => {
        const isSelected = selectedSectorIndexes.has(section.sectorIndex)
        return (
          <CollapsibleSection
            key={section.sectorIndex}
            title={section.title}
            titleHover={section.titleHover}
            compact={compact}
            expandLabelNoun="sector"
            borderClassName={
              isSelected ? 'border-2 border-sky-400/80' : 'border border-[#52575d]'
            }
            dataAttrs={{
              'data-sector-index': String(section.sectorIndex),
              'data-selected': isSelected ? 'true' : 'false',
            }}
            titleControl={
              <button
                type="button"
                title={section.titleHover ?? undefined}
                aria-pressed={isSelected}
                aria-label={`Toggle sector selection: ${section.title}`}
                className={cn(
                  'min-w-0 flex-1 truncate text-left font-medium text-slate-200 hover:text-white',
                  compact ? 'px-0.5 py-0.5 text-[11px]' : 'px-1 py-1 text-sm'
                )}
                onClick={() => onToggleSectorIndex(section.sectorIndex)}
              >
                {section.title}
              </button>
            }
          >
            <HomeworldCandidateRows
              {...candidateRowsProps}
              rows={section.candidates}
              showOwnerColumn={false}
              possibleOwners={section.overlay.possibleOwners}
              ownershipWinningStrength={section.overlay.ownershipWinningStrength}
            />
          </CollapsibleSection>
        )
      })}
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

/**
 * Player accordion: one collapsible section per roster player (playerId order).
 * Sparse candidates -- pinned/asserted rows only; no Unassigned dump.
 */
export function HomeworldPlayerAccordion({
  sections,
  baselineDegraded,
  baselineTurn,
  roster,
  onSelectPlanet,
  compact = false,
}: HomeworldPlayerAccordionProps) {
  return (
    <div className={cn('flex flex-col', compact ? 'gap-1' : 'gap-2')}>
      <BaselineBanner
        baselineDegraded={baselineDegraded}
        baselineTurn={baselineTurn}
        compact={compact}
      />
      {sections.map((section) => (
        <CollapsibleSection
          key={section.playerOrdinal}
          title={section.title}
          compact={compact}
          expandLabelNoun="player"
          borderClassName="border border-[#52575d]"
          dataAttrs={{
            'data-player-ordinal': String(section.playerOrdinal),
            'data-player-id': String(section.playerId),
          }}
        >
          <HomeworldCandidateRows
            rows={section.candidates}
            baselineDegraded={false}
            baselineTurn={baselineTurn}
            roster={roster}
            onSelectPlanet={onSelectPlanet}
            compact={compact}
            showHeader={!compact}
            showOwnerColumn={false}
            emptyMessage="No pinned homeworld."
          />
        </CollapsibleSection>
      ))}
    </div>
  )
}
