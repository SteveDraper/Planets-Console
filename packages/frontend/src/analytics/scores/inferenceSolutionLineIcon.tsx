import {
  HelpCircle,
  Rocket,
  Shield,
  Swords,
} from 'lucide-react'
import type { ScoresInferenceSolutionShipBuild } from '../../api/bff'
import {
  GENERIC_FREIGHTER_HULL_ID,
  hullImageUrl,
} from '../../concepts/hullImageUrl'
import type { MilitaryScoreLineItem } from './inferenceConstraints'

const GENERIC_FREIGHTER_COMBO_ID = 'combo_freighter'

function parseHullIdFromComboId(comboId: string): number | null {
  if (comboId === GENERIC_FREIGHTER_COMBO_ID) {
    return GENERIC_FREIGHTER_HULL_ID
  }
  const match = /^combo_(\d+)_/.exec(comboId)
  if (match == null) {
    return null
  }
  return Number(match[1])
}

function resolveShipBuildForLine(
  line: MilitaryScoreLineItem,
  shipBuilds: ScoresInferenceSolutionShipBuild[] | undefined
): ScoresInferenceSolutionShipBuild | null {
  if (shipBuilds == null || shipBuilds.length === 0) {
    return null
  }
  const byCombo = shipBuilds.find((build) => build.comboId === line.actionId)
  if (byCombo != null) {
    return byCombo
  }
  if (shipBuilds.length === 1 && line.actionId.startsWith('combo_')) {
    return shipBuilds[0] ?? null
  }
  return null
}

function resolveHullIdForLine(
  line: MilitaryScoreLineItem,
  shipBuild: ScoresInferenceSolutionShipBuild | null
): number | null {
  if (shipBuild?.hullId != null && shipBuild.hullId > 0) {
    return shipBuild.hullId
  }
  if (line.actionId.startsWith('combo_')) {
    return parseHullIdFromComboId(line.actionId)
  }
  return null
}

function aggregateActionIcon(actionId: string) {
  if (actionId.startsWith('ship_torps_loaded_')) {
    return Rocket
  }
  if (
    actionId.includes('fighter') ||
    actionId.startsWith('fighters_')
  ) {
    return Swords
  }
  if (actionId.includes('defense')) {
    return Shield
  }
  return HelpCircle
}

type InferenceSolutionLineIconProps = {
  line: MilitaryScoreLineItem
  shipBuilds: ScoresInferenceSolutionShipBuild[] | undefined
}

export function InferenceSolutionLineIcon({
  line,
  shipBuilds,
}: InferenceSolutionLineIconProps) {
  const shipBuild = resolveShipBuildForLine(line, shipBuilds)
  const hullId = resolveHullIdForLine(line, shipBuild)

  if (hullId != null) {
    const beams =
      shipBuild != null &&
      shipBuild.beamCount != null &&
      shipBuild.beamCount > 0 &&
      (hullId === 65 || hullId === 71)
        ? shipBuild.beamCount
        : undefined
    return (
      <img
        src={hullImageUrl(hullId, { beams })}
        alt=""
        className="h-8 w-8 object-contain"
        loading="lazy"
      />
    )
  }

  const Icon = aggregateActionIcon(line.actionId)
  return <Icon className="h-5 w-5 text-slate-400" aria-hidden />
}
