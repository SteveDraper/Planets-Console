import { HullIcon } from '../../components/HullIcon'
import type { FleetHullDisplay } from './fleetRecordComponentDisplay'

type FleetRecordHullCellProps = {
  hull: FleetHullDisplay
}

export function FleetRecordHullCell({ hull }: FleetRecordHullCellProps) {
  return (
    <span className="inline-flex items-center gap-2">
      {hull.hullId != null ? (
        <HullIcon hullId={hull.hullId} className="h-7 w-7 shrink-0" />
      ) : null}
      <span>{hull.label}</span>
    </span>
  )
}
