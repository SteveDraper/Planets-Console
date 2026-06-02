import { useState } from 'react'
import { Check, Hourglass, X } from 'lucide-react'
import type { TableDataResponse } from '../../api/bff'
import { InferenceDetailModal } from './InferenceDetailModal'
import {
  canOpenInferenceDetail,
  inferenceAccessibleLabel,
} from './inferenceStatus'

type ScoresTableViewProps = {
  data: TableDataResponse
}

function InferenceStatusCell({
  detail,
  onOpenDetail,
}: {
  detail: NonNullable<TableDataResponse['inferenceByRow']>[number]
  onOpenDetail: () => void
}) {
  const label = inferenceAccessibleLabel(detail)
  if (detail.displayStatus === 'success') {
    const clickable = canOpenInferenceDetail(detail)
    return (
      <button
        type="button"
        title={label}
        aria-label={label}
        disabled={!clickable}
        onClick={clickable ? onOpenDetail : undefined}
        className="inline-flex items-center justify-center rounded p-1 text-emerald-400 hover:bg-white/10 disabled:cursor-default disabled:opacity-60"
      >
        <Check className="h-4 w-4" aria-hidden />
      </button>
    )
  }
  if (detail.displayStatus === 'pending') {
    return (
      <span
        title={label}
        aria-label={label}
        className="inline-flex items-center justify-center p-1 text-amber-300"
      >
        <Hourglass className="h-4 w-4" aria-hidden />
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

export function ScoresTableView({ data }: ScoresTableViewProps) {
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
                {row.map((cell, columnIndex) => {
                  const isInferenceColumn =
                    data.includeBuildInference === true &&
                    inferenceByRow != null &&
                    columnIndex === row.length - 1
                  if (isInferenceColumn) {
                    return (
                      <td key={columnIndex} className="px-3 py-2 text-gray-400">
                        <InferenceStatusCell
                          detail={inferenceByRow[rowIndex]}
                          onOpenDetail={() => setSelectedRowIndex(rowIndex)}
                        />
                      </td>
                    )
                  }
                  return (
                    <td key={columnIndex} className="px-3 py-2 text-gray-400">
                      {cell}
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
