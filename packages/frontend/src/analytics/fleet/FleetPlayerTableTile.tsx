import { Fragment, useMemo, useState } from 'react'
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table'
import { AlertTriangle, ChevronDown, ShieldCheck } from 'lucide-react'
import { cn } from '../../lib/utils'
import {
  activeFleetRecords,
  alternateBuildOptionSets,
  formatBuildOptionSetSummary,
  formatFleetCountDiscrepancyBanner,
  formatFleetLastSeen,
  formatFleetRecordField,
} from './fleetRecordDisplay'
import type { FleetCountDiscrepancy, FleetTableRecord } from './fleetTableWireSchema'

type FleetPlayerTableTileProps = {
  playerName: string
  records: readonly FleetTableRecord[]
  discrepancy?: FleetCountDiscrepancy
}

const columnHelper = createColumnHelper<FleetTableRecord>()

function FleetStatusIcons({ record }: { record: FleetTableRecord }) {
  const possiblyLost = record.qualifiers.possiblyLost
  const alibi = record.qualifiers.alibi

  if (possiblyLost == null && alibi == null) {
    return <span className="text-slate-500">—</span>
  }

  return (
    <div className="inline-flex items-center gap-1">
      {possiblyLost != null ? (
        <span
          title={`Possibly lost since turn ${possiblyLost.sinceTurn} (${possiblyLost.source})`}
          aria-label={`Possibly lost since turn ${possiblyLost.sinceTurn}`}
          className="inline-flex text-amber-400"
        >
          <AlertTriangle className="h-4 w-4" aria-hidden />
        </span>
      ) : null}
      {alibi != null ? (
        <span
          title={`Alibi: sighting turn ${alibi.sightingTurn} after turn ${alibi.afterTurn} (${alibi.source})`}
          aria-label={`Alibi after turn ${alibi.afterTurn}`}
          className="inline-flex text-emerald-400"
        >
          <ShieldCheck className="h-4 w-4" aria-hidden />
        </span>
      ) : null}
    </div>
  )
}

export function FleetPlayerTableTile({
  playerName,
  records,
  discrepancy,
}: FleetPlayerTableTileProps) {
  const [expandedRecordIds, setExpandedRecordIds] = useState<ReadonlySet<string>>(() => new Set())
  const activeRecords = useMemo(() => activeFleetRecords(records), [records])

  const columns = useMemo(
    () => [
      columnHelper.display({
        id: 'expander',
        header: '',
        cell: ({ row }) => {
          const alternates = alternateBuildOptionSets(row.original)
          if (alternates.length === 0) {
            return null
          }
          const expanded = expandedRecordIds.has(row.original.recordId)
          return (
            <button
              type="button"
              aria-expanded={expanded}
              aria-label={
                expanded
                  ? `Collapse build options for ${row.original.recordId}`
                  : `Expand build options for ${row.original.recordId}`
              }
              onClick={() =>
                setExpandedRecordIds((current) => {
                  const next = new Set(current)
                  if (next.has(row.original.recordId)) {
                    next.delete(row.original.recordId)
                  } else {
                    next.add(row.original.recordId)
                  }
                  return next
                })
              }
              className="inline-flex h-6 w-6 items-center justify-center rounded text-slate-400 hover:bg-black/15 hover:text-slate-200"
            >
              <ChevronDown
                className={cn(
                  'h-4 w-4 transition-transform duration-150',
                  !expanded && '-rotate-90'
                )}
                aria-hidden
              />
            </button>
          )
        },
      }),
      columnHelper.accessor((record) => formatFleetRecordField(record, 'shipId'), {
        id: 'shipId',
        header: 'ID',
      }),
      columnHelper.accessor((record) => formatFleetRecordField(record, 'hull'), {
        id: 'hull',
        header: 'Hull',
      }),
      columnHelper.accessor((record) => formatFleetRecordField(record, 'engine'), {
        id: 'engine',
        header: 'Engine',
      }),
      columnHelper.accessor((record) => formatFleetRecordField(record, 'beams'), {
        id: 'beams',
        header: 'Beams',
      }),
      columnHelper.accessor((record) => formatFleetRecordField(record, 'launchers'), {
        id: 'launchers',
        header: 'Launchers',
      }),
      columnHelper.accessor((record) => formatFleetRecordField(record, 'builtTurn'), {
        id: 'builtTurn',
        header: 'Built',
      }),
      columnHelper.accessor((record) => formatFleetLastSeen(record.lastSeen), {
        id: 'lastSeen',
        header: 'Last seen',
      }),
      columnHelper.display({
        id: 'status',
        header: 'Status',
        cell: ({ row }) => <FleetStatusIcons record={row.original} />,
      }),
    ],
    [expandedRecordIds]
  )

  const table = useReactTable({
    data: activeRecords,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (record) => record.recordId,
  })

  return (
    <section
      className="rounded-md border border-[#52575d]/80 bg-[#3a3f44]"
      aria-label={`${playerName} fleet table`}
    >
      <header className="border-b border-[#52575d]/70 px-4 py-2">
        <h3 className="text-sm font-medium text-slate-200">{playerName}</h3>
        {discrepancy != null ? (
          <p
            role="status"
            className="mt-1 text-xs text-amber-300"
            aria-label={formatFleetCountDiscrepancyBanner(
              discrepancy.activeRowCount,
              discrepancy.scoreboardImpliedCount,
              discrepancy.hostTurn
            )}
          >
            {formatFleetCountDiscrepancyBanner(
              discrepancy.activeRowCount,
              discrepancy.scoreboardImpliedCount,
              discrepancy.hostTurn
            )}
          </p>
        ) : null}
      </header>
      {activeRecords.length === 0 ? (
        <p className="px-4 py-3 text-sm text-slate-400">No active fleet records.</p>
      ) : (
        <div className="overflow-auto">
          <table className="min-w-full border-collapse text-sm">
            <thead>
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id} className="border-b border-[#52575d]/70">
                  {headerGroup.headers.map((header) => (
                    <th
                      key={header.id}
                      className="px-3 py-2 text-left font-medium text-slate-300"
                    >
                      {header.isPlaceholder
                        ? null
                        : flexRender(header.column.columnDef.header, header.getContext())}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => {
                const alternates = alternateBuildOptionSets(row.original)
                const expanded = expandedRecordIds.has(row.original.recordId)
                return (
                  <Fragment key={row.id}>
                    <tr className="border-b border-[#52575d]/50">
                      {row.getVisibleCells().map((cell) => (
                        <td key={cell.id} className="px-3 py-2 text-gray-400">
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </tr>
                    {expanded && alternates.length > 0 ? (
                      <tr key={`${row.id}-alternates`} className="border-b border-[#52575d]/50">
                        <td
                          colSpan={columns.length}
                          className="bg-black/10 px-3 py-2 text-xs text-slate-300"
                        >
                          <ul className="space-y-1">
                            {alternates.map((optionSet) => (
                              <li key={optionSet.comboId ?? optionSet.label}>
                                {formatBuildOptionSetSummary(optionSet)}
                              </li>
                            ))}
                          </ul>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
