import { useState } from 'react'
import { Hourglass, Octagon, Square, X } from 'lucide-react'
import type { ScoresInferenceRowDetail, ScoresTableWithInferenceData } from '../../api/bff'
import { InferenceDetailModal } from './InferenceDetailModal'
import {
  canHaltInferenceRow,
  canOpenInferenceDetail,
  inferenceAccessibleLabel,
} from './inferenceStatus'
import {
  isBuildInferenceColumn,
  scoresTableCellForColumn,
} from './scoresTableColumns'

type ScoresTableViewProps = {
  data: ScoresTableWithInferenceData
  onHaltRow?: (playerId: number) => void
}

function InferenceStatusCell({
  detail,
  onOpenDetail,
  onHaltRow,
}: {
  detail: ScoresInferenceRowDetail
  onOpenDetail: () => void
  onHaltRow?: (playerId: number) => void
}) {
  const label = inferenceAccessibleLabel(detail)
  const playerId = detail.playerId
  const showHalt = canHaltInferenceRow(detail) && typeof playerId === 'number'

  if (detail.displayStatus === 'success' && detail.solutionCount > 0) {
    const clickable = canOpenInferenceDetail(detail)
    return (
      <div className="inline-flex items-center gap-1">
        <button
          type="button"
          title={label}
          aria-label={label}
          disabled={!clickable}
          onClick={clickable ? onOpenDetail : undefined}
          className="inline-flex h-6 min-w-6 items-center justify-center rounded border border-emerald-500/70 px-1.5 text-xs font-medium text-emerald-400 hover:bg-white/10 disabled:cursor-default disabled:opacity-60"
        >
          {detail.solutionCount}
        </button>
        {showHalt && onHaltRow != null ? (
          <button
            type="button"
            title="Stop build inference for this row"
            aria-label="Stop build inference for this row"
            onClick={() => onHaltRow(playerId)}
            className="inline-flex items-center justify-center rounded p-1 text-slate-300 hover:bg-white/10"
          >
            <Square className="h-3.5 w-3.5" aria-hidden />
          </button>
        ) : null}
        {!detail.isComplete ? (
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400/80" aria-hidden />
        ) : null}
      </div>
    )
  }

  if (detail.displayStatus === 'pending') {
    return (
      <div className="inline-flex items-center gap-1">
        <span
          title={label}
          aria-label={label}
          className="inline-flex items-center justify-center p-1 text-amber-300"
        >
          <Hourglass className="h-4 w-4" aria-hidden />
        </span>
        {showHalt && onHaltRow != null ? (
          <button
            type="button"
            title="Stop build inference for this row"
            aria-label="Stop build inference for this row"
            onClick={() => onHaltRow(playerId)}
            className="inline-flex items-center justify-center rounded p-1 text-slate-300 hover:bg-white/10"
          >
            <Square className="h-3.5 w-3.5" aria-hidden />
          </button>
        ) : null}
      </div>
    )
  }

  if (detail.displayStatus === 'stopped') {
    return (
      <span
        title={label}
        aria-label={label}
        className="inline-flex items-center justify-center p-1 text-slate-400"
      >
        <Octagon className="h-4 w-4" aria-hidden />
      </span>
    )
  }

  return (
    <span
      title={label}
      aria-label={label}
      className="inline-flex items-center justify-center p-1 text-red-400"
    >
      <X className="h-4 w-4" aria-hidden />
    </span>
  )
}

export function ScoresTableView({ data, onHaltRow }: ScoresTableViewProps) {
  const [selectedRowIndex, setSelectedRowIndex] = useState<number | null>(null)
  const inferenceByRow = data.inferenceByRow
  const selectedDetail =
    selectedRowIndex != null && inferenceByRow != null
      ? inferenceByRow[selectedRowIndex]
      : null
  const selectedRacePlayer =
    selectedRowIndex != null ? data.rows[selectedRowIndex]?.[0] ?? '' : ''

  return (
    <>
      <div className="overflow-auto">
        <table className="min-w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-[#52575d]">
              {data.columns.map((column) => (
                <th key={column} className="px-3 py-2 text-left font-medium text-slate-200">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row, rowIndex) => (
              <tr key={rowIndex} className="border-b border-[#52575d]/60">
                {data.columns.map((column) => {
                  if (isBuildInferenceColumn(column) && inferenceByRow != null) {
                    return (
                      <td key={column} className="px-3 py-2 text-gray-400">
                        <InferenceStatusCell
                          detail={inferenceByRow[rowIndex]}
                          onOpenDetail={() => setSelectedRowIndex(rowIndex)}
                          onHaltRow={onHaltRow}
                        />
                      </td>
                    )
                  }
                  return (
                    <td key={column} className="px-3 py-2 text-gray-400">
                      {scoresTableCellForColumn(row, column)}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <InferenceDetailModal
        isOpen={selectedRowIndex != null}
        onClose={() => setSelectedRowIndex(null)}
        racePlayer={selectedRacePlayer}
        detail={selectedDetail}
      />
    </>
  )
}
