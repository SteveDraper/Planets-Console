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
import {
  HOMEWORLD_REGION_DISPLAY_MODE_LABELS,
  HOMEWORLD_REGION_DISPLAY_MODES,
  type HomeworldRegionDisplayMode,
} from './homeworldRegionDisplayMode'
import { useHomeworldRegionDisplayStore } from '../../stores/homeworldRegionDisplay'
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

function HomeworldRegionDisplayModeControl({
  value,
  onChange,
}: {
  value: HomeworldRegionDisplayMode
  onChange: (mode: HomeworldRegionDisplayMode) => void
}) {
  return (
    <DisplayModeControl
      label="Region overlays"
      ariaLabel="Homeworld region display mode"
      modes={HOMEWORLD_REGION_DISPLAY_MODES}
      modeLabels={HOMEWORLD_REGION_DISPLAY_MODE_LABELS}
      value={value}
      onChange={onChange}
    />
  )
}

/**
 * Sidebar enable toggle for Homeworld locator with expandable panel
 * (region display mode, candidate table, assert/revoke, refresh).
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
  const regionDisplayMode = useHomeworldRegionDisplayStore((s) => s.regionDisplayMode)
  const setRegionDisplayMode = useHomeworldRegionDisplayStore((s) => s.setRegionDisplayMode)

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
  const setSelection = useHomeworldLocatorSelectionStore((s) => s.setSelection)

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

  const showExpandedBody = canExpand && expanded
  const chevronPointsDown = showExpandedBody
  const selectedPlanetId = selection?.kind === 'planet' ? selection.planetId : null

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
          <HomeworldRegionDisplayModeControl
            value={regionDisplayMode}
            onChange={setRegionDisplayMode}
          />
          <HomeworldLocatorPanel
            analyticScope={analyticScope}
            fetchEnabled={canExpand}
            roster={roster}
            selectedPlanetId={selectedPlanetId}
            onSelectPlanet={(planetId) => setSelection({ kind: 'planet', planetId })}
          />
        </div>
      ) : null}
    </div>
  )
}
