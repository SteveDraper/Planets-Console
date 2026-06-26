import { hullImageUrl } from '../../concepts/hullImageUrl'
import type { FleetHullDisplay } from './fleetRecordComponentDisplay'

type FleetRecordHullCellProps = {
  hull: FleetHullDisplay
}

export function FleetRecordHullCell({ hull }: FleetRecordHullCellProps) {
  return (
    <span className="inline-flex items-center gap-2">
      {hull.hullId != null ? (
        <img
          src={hullImageUrl(hull.hullId)}
          alt=""
          className="h-7 w-7 shrink-0 object-contain"
          loading="lazy"
        />
      ) : null}
      <span>{hull.label}</span>
    </span>
  )
}
