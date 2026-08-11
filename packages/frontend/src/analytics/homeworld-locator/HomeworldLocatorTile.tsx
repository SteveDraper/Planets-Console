import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '../../lib/utils'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { tileClassName } from '../tileChrome'
import { DisplayModeControl } from '../DisplayModeControl'
import { deriveAnalyticScope } from '../../shell/shellContext'
import { useSessionStore } from '../../stores/session'
import { useShellStore } from '../../stores/shell'
import { useHomeworldLocatorSelectionStore } from '../../stores/homeworldLocatorSelection'
import { homeworldInactiveHint } from './constants'
import { selectHomeworldCandidateForMapAttention } from './homeworldCandidateAttention'
import {
  HOMEWORLD_REGION_SELECTION_PRESET_LABELS,
  HOMEWORLD_REGION_SELECTION_UI_PRESETS,
  type HomeworldRegionSelectionUiPreset,
} from '../../lib/homeworldRegionSelection'
import { homeworldSectorsPresentOnMap } from './homeworldSectorIndex'
import { useBaseMapPlanetPositions } from './useBaseMapPlanetPositions'
import { useHomeworldLocatorMapOverlays } from './useHomeworldLocatorMapOverlays'
import { useHomeworldRegionSelection } from './useHomeworldRegionSelection'
import { HomeworldLocatorPanel } from './HomeworldLocatorPanel'

const EMPTY_ROSTER: readonly PerspectiveRow[] = []

type HomeworldLocatorTileProps = {
  name: string
  enabled: boolean
  supportsMode: boolean
  depressed: boolean
  onToggle: () => void
  /** When set, catalog is greyed and toggle is disabled (no traditional homeworlds). */
  inactiveReason: string | null
}

function HomeworldRegionSelectionControl({
  value,
  onChange,
}: {
  value: HomeworldRegionSelectionUiPreset
  onChange: (preset: HomeworldRegionSelectionUiPreset) => void
}) {
  return (
    <DisplayModeControl
      label="Region selection"
      ariaLabel="Homeworld region selection"
      modes={HOMEWORLD_REGION_SELECTION_UI_PRESETS}
      modeLabels={HOMEWORLD_REGION_SELECTION_PRESET_LABELS}
      value={value}
      onChange={onChange}
    />
  )
}

/**
 * Sidebar enable toggle for Homeworld locator with expandable panel
 * (region selection, envelope overlays, read-only candidates, refresh).
 * Assert/revoke is map-context-menu only.
 */
export function HomeworldLocatorTile({
  name,
  enabled,
  supportsMode,
  depressed,
  onToggle,
  inactiveReason,
}: HomeworldLocatorTileProps) {
  const available = inactiveReason == null
  const canToggle = supportsMode && available
  const showAsUnsupported = !canToggle
  const hint = available ? undefined : homeworldInactiveHint(inactiveReason)

  const [expanded, setExpanded] = useState(false)
  const canExpand = canToggle && enabled

  const selectedGameId = useShellStore((s) => s.selectedGameId)
  const gameInfoContext = useShellStore((s) => s.gameInfoContext)
  const selectedTurn = useShellStore((s) => s.selectedTurn)
  const perspectiveOverrideOrdinal = useShellStore((s) => s.perspectiveOverrideOrdinal)
  const storageOnlyLoad = useShellStore((s) => s.storageOnlyLoad)
  const storageAvailablePerspectives = useShellStore((s) => s.storageAvailablePerspectives)
  const loginName = useSessionStore((s) => s.name)
  const perspectives = gameInfoContext?.perspectives
  const roster = perspectives ?? EMPTY_ROSTER
  const selection = useHomeworldLocatorSelectionStore((s) => s.selection)
  const selectedPlanetId = selection?.kind === 'planet' ? selection.planetId : null

  const analyticScope = deriveAnalyticScope({
    selectedGameId,
    gameInfoContext,
    selectedTurn,
    perspectiveOverrideOrdinal,
    loginName,
    storageOnlyLoad,
    storageAvailablePerspectives,
    viewedDataTurn: selectedTurn,
    turnUsernamesByPlayerId: null,
  })

  const { overlays, homeworldMapOverlaysQuerySucceeded, overlaysError } =
    useHomeworldLocatorMapOverlays({
      analyticScope,
      fetchEnabled: canExpand,
    })

  const {
    uiPreset,
    showEnvelopeOverlays,
    setUiPreset,
    setShowEnvelopeOverlays,
    selectedSectorIndexSet,
    toggleSectorIndex,
  } = useHomeworldRegionSelection({ overlays })

  const needsPlanetPositions = overlays.length > 0
  const { planetPositions, positionsReady, positionsError } = useBaseMapPlanetPositions({
    analyticScope,
    fetchEnabled: canExpand && needsPlanetPositions,
  })

  const showExpandedBody = canExpand && expanded
  const chevronPointsDown = showExpandedBody
  // Region selection is sector-outline chrome; hide in player-tile mode (no sectors).
  const showRegionSelection =
    homeworldMapOverlaysQuerySucceeded && homeworldSectorsPresentOnMap(overlays)

  return (
    <div
      title={hint}
      className={cn(
        tileClassName({
          supportsMode: !showAsUnsupported,
          depressed: depressed && canToggle,
        }),
        'flex min-w-0 max-w-full flex-col',
        showAsUnsupported && 'cursor-default'
      )}
    >
      <div className="flex items-center gap-1 py-1.5 pl-2 pr-0.5">
        <label
          className={cn(
            'flex min-w-0 flex-1 cursor-pointer items-center gap-2 py-0.5',
            showAsUnsupported && 'cursor-default'
          )}
        >
          <input
            type="checkbox"
            checked={enabled && available}
            onChange={() => canToggle && onToggle()}
            disabled={!canToggle}
            className="h-4 w-4 shrink-0 rounded border-[#52575d] bg-slate-700 text-slate-200 accent-slate-400 focus:ring-[#52575d] focus:ring-offset-0"
          />
          <span className="min-w-0 truncate">{name}</span>
        </label>
        <button
          type="button"
          aria-expanded={chevronPointsDown}
          aria-label={
            chevronPointsDown
              ? 'Collapse Homeworld locator options'
              : 'Expand Homeworld locator options'
          }
          disabled={!canExpand}
          onClick={() => canExpand && setExpanded((v) => !v)}
          className={cn(
            'flex h-7 w-7 shrink-0 items-center justify-center rounded text-slate-400 transition-colors',
            canExpand &&
              'hover:bg-black/15 hover:text-slate-200 focus-visible:outline focus-visible:ring-1 focus-visible:ring-slate-500',
            !canExpand && 'cursor-default opacity-40'
          )}
        >
          <ChevronDown
            className={cn(
              'h-4 w-4 shrink-0 transition-transform duration-150',
              !chevronPointsDown && '-rotate-90'
            )}
            aria-hidden
          />
        </button>
      </div>
      {showExpandedBody ? (
        <div
          className="flex min-w-0 flex-col gap-1.5 border-t border-[#52575d]/70 px-2 pb-2 pt-1.5 text-xs text-slate-300"
          onClick={(e) => e.stopPropagation()}
        >
          <label className="flex cursor-pointer items-center gap-2 py-0.5">
            <input
              type="checkbox"
              checked={showEnvelopeOverlays}
              onChange={(e) => setShowEnvelopeOverlays(e.target.checked)}
              aria-label="Show overlays"
              className="h-4 w-4 shrink-0 rounded border-[#52575d] bg-slate-700 text-slate-200 accent-slate-400 focus:ring-[#52575d] focus:ring-offset-0"
            />
            <span>Show overlays</span>
          </label>
          {showRegionSelection ? (
            <HomeworldRegionSelectionControl
              value={uiPreset}
              onChange={setUiPreset}
            />
          ) : null}
          <HomeworldLocatorPanel
            analyticScope={analyticScope}
            fetchEnabled={canExpand}
            roster={roster}
            selectedPlanetId={selectedPlanetId}
            onSelectPlanet={selectHomeworldCandidateForMapAttention}
            selectedSectorIndexes={selectedSectorIndexSet}
            onToggleSectorIndex={toggleSectorIndex}
            overlays={overlays}
            homeworldMapOverlaysQuerySucceeded={homeworldMapOverlaysQuerySucceeded}
            overlaysError={overlaysError}
            planetPositions={planetPositions}
            positionsReady={positionsReady}
            positionsError={positionsError}
          />
        </div>
      ) : null}
    </div>
  )
}
