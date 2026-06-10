import type { ScoresInferenceSolutionShipBuild } from '../../api/bff'
import {
  GENERIC_FREIGHTER_HULL_ID,
  hullImageUrl,
} from '../../concepts/hullImageUrl'
import { inferenceActionAggregateIcon } from './inferenceActionFamily'
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
  return shipBuilds.find((build) => build.comboId === line.actionId) ?? null
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
    return (
      <img
        src={hullImageUrl(hullId)}
        alt=""
        className="h-8 w-8 object-contain"
        loading="lazy"
      />
    )
  }

  const Icon = inferenceActionAggregateIcon(line.actionId)
  return <Icon className="h-5 w-5 text-slate-400" aria-hidden />
}
