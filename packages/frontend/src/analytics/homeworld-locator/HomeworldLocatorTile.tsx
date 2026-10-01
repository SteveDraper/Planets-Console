import type { AnalyticShellScope } from '../../api/bff'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { AnalyticSidebarTile } from '../AnalyticSidebarTile'
import { DisplayModeControl } from '../DisplayModeControl'
import { useShellStore } from '../../stores/shell'
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
  /**
   * True when the shell turn blob is in storage (ensure succeeded).
   * Sidebar table/map GETs must wait for this -- same gate as MainArea.
   */
  turnDataReady: boolean
  analyticScope: AnalyticShellScope | null
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
  turnDataReady,
  analyticScope,
}: HomeworldLocatorTileProps) {
  const inactiveReason =
    useShellStore((s) => s.gameInfoContext?.homeworldInactiveReason) ?? null
  const available = inactiveReason == null
  const canToggle = supportsMode && available
  const hint = available ? undefined : homeworldInactiveHint(inactiveReason)

  const canLoad = canToggle && enabled
  const fetchEnabled = canLoad && turnDataReady

  const perspectives = useShellStore((s) => s.gameInfoContext?.perspectives)
  const roster = perspectives ?? EMPTY_ROSTER

  const { overlays, homeworldMapOverlaysQuerySucceeded, overlaysError } =
    useHomeworldLocatorMapOverlays({
      analyticScope,
      fetchEnabled,
    })

  const {
    uiPreset,
    showEnvelopeOverlays,
    setUiPreset,
    setShowEnvelopeOverlays,
    selectedSectorIndexSet,
    toggleSectorIndex,
  } = useHomeworldRegionSelection({ overlays })

  // Sector accordion groups by map position; planet envelopes do not need base-map.
  const needsPlanetPositions = homeworldSectorsPresentOnMap(overlays)
  const { planetPositions, positionsReady, positionsError } = useBaseMapPlanetPositions({
    analyticScope,
    fetchEnabled: fetchEnabled && needsPlanetPositions,
  })

  // Region selection is sector-outline chrome; hide in player-tile mode (no sectors).
  const showRegionSelection =
    homeworldMapOverlaysQuerySucceeded && homeworldSectorsPresentOnMap(overlays)

  return (
    <AnalyticSidebarTile
      name={name}
      enabled={enabled}
      supportsMode={supportsMode}
      depressed={depressed}
      onToggle={onToggle}
      available={available}
      hint={hint}
      detailsLabel="Homeworld locator options"
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
        fetchEnabled={fetchEnabled}
        roster={roster}
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
    </AnalyticSidebarTile>
  )
}
