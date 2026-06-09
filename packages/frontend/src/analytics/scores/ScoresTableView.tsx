import { useState } from 'react'
import { Octagon, X } from 'lucide-react'
import type {
  AnalyticShellScope,
  ScoresInferenceRowDetail,
  ScoresTableWithInferenceData,
} from '../../api/bff'
import { GlobalInferencePauseControl } from './GlobalInferencePauseControl'
import { InferenceDetailModal } from './InferenceDetailModal'
import { InferenceSolutionCountBadge } from './InferenceSolutionCountBadge'
import {
  canOpenInferenceDetail,
  inferenceAccessibleLabel,
  isActivelySearchingInference,
  isIncompleteInferenceRow,
} from './inferenceStatus'
import {
  BUILD_INFERENCE_COLUMN,
  isBuildInferenceColumn,
  scoresTableCellForColumn,
} from './scoresTableColumns'
import type { UseGlobalInferencePauseResult } from './useGlobalInferencePause'

type ScoresTableViewProps = {
  data: ScoresTableWithInferenceData
  analyticScope: AnalyticShellScope
  isGloballyPaused?: boolean
  globalInferencePause?: UseGlobalInferencePauseResult
}

function InferenceStatusCell({
  detail,
  onOpenDetail,
  isGloballyPaused = false,
}: {
  detail: ScoresInferenceRowDetail
  onOpenDetail: () => void
  isGloballyPaused?: boolean
}) {
  const label = inferenceAccessibleLabel(detail)

  if (isIncompleteInferenceRow(detail)) {
    const activelySearching = isActivelySearchingInference(detail, isGloballyPaused)
    return (
      <div className="inline-flex items-center gap-1">
        <InferenceSolutionCountBadge
          count={detail.solutionCount}
          isSearching={activelySearching}
          isIncomplete
          label={label}
          disabled={!canOpenInferenceDetail(detail)}
          onClick={canOpenInferenceDetail(detail) ? onOpenDetail : undefined}
        />
      </div>
    )
  }

  if (detail.displayStatus === 'success' && detail.solutionCount > 0) {
    return (
      <div className="inline-flex items-center gap-1">
        <InferenceSolutionCountBadge
          count={detail.solutionCount}
          isSearching={false}
          label={label}
          disabled={!canOpenInferenceDetail(detail)}
          onClick={canOpenInferenceDetail(detail) ? onOpenDetail : undefined}
        />
      </div>
    )
  }

  if (detail.displayStatus === 'stopped') {
    return (
      <div className="inline-flex items-center gap-1">
        <span
          title={label}
          aria-label={label}
          className="inline-flex items-center justify-center p-1 text-slate-400"
        >
          <Octagon className="h-4 w-4" aria-hidden />
        </span>
      </div>
    )
  }

  return (
    <div className="inline-flex items-center gap-1">
      <span
        title={label}
        aria-label={label}
        className="inline-flex items-center justify-center p-1 text-red-400"
      >
        <X className="h-4 w-4" aria-hidden />
      </span>
    </div>
  )
}

export function ScoresTableView({
  data,
  analyticScope: _analyticScope,
  isGloballyPaused = false,
  globalInferencePause,
}: ScoresTableViewProps) {
  const [selectedRowIndex, setSelectedRowIndex] = useState<number | null>(null)
  const inferenceByRow = data.inferenceByRow
  const selectedDetail =
    selectedRowIndex != null && inferenceByRow != null
      ? inferenceByRow[selectedRowIndex]
      : null
  const selectedRacePlayer =
    selectedRowIndex != null ? data.rows[selectedRowIndex]?.[0] ?? '' : ''

  const showGlobalPauseControl =
    data.includeBuildInference && globalInferencePause != null

  return (
    <>
      <div className="max-h-[calc(100dvh-14rem)] overflow-auto overscroll-contain">
        <table className="min-w-full border-separate border-spacing-0 text-sm">
          <thead>
            <tr>
              {data.columns.map((column) => (
                <th
                  key={column}
                  className="sticky top-0 z-10 bg-[#40454a] px-3 py-2 text-left font-medium text-slate-200 shadow-[inset_0_-1px_0_#52575d]"
                >
                  {column === BUILD_INFERENCE_COLUMN && showGlobalPauseControl ? (
                    <span className="inline-flex items-center gap-1.5">
                      <span>{column}</span>
                      <GlobalInferencePauseControl globalInferencePause={globalInferencePause} />
                    </span>
                  ) : (
                    column
                  )}
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
                          isGloballyPaused={isGloballyPaused}
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
