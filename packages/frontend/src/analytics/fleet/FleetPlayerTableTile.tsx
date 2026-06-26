import { Fragment, useMemo, useState } from 'react'
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getExpandedRowModel,
  useReactTable,
  type ExpandedState,
} from '@tanstack/react-table'
import { AlertTriangle, ChevronDown, ShieldCheck } from 'lucide-react'
import { cn } from '../../lib/utils'
import {
  EMPTY_FLEET_COMPONENT_CATALOG,
  type FleetComponentCatalog,
} from './fleetTableWireSchema'
import {
  activeFleetRecords,
  alternateBuildOptionSets,
  formatFleetCountDiscrepancyBanner,
  formatFleetLastSeen,
  formatFleetRecordField,
} from './fleetRecordDisplay'
import {
  formatBuildOptionSetComponentSummary,
  formatFleetBeamsDisplay,
  formatFleetEngineDisplay,
  formatFleetHullDisplay,
  formatFleetLaunchersDisplay,
} from './fleetRecordComponentDisplay'
import { FleetRecordHullCell } from './FleetRecordHullCell'
import type { FleetCountDiscrepancy, FleetTableRecord } from './fleetTableWireSchema'

type FleetPlayerTableTileProps = {
  playerName: string
  records: readonly FleetTableRecord[]
  discrepancy?: FleetCountDiscrepancy
  componentCatalog?: FleetComponentCatalog
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
  componentCatalog = EMPTY_FLEET_COMPONENT_CATALOG,
}: FleetPlayerTableTileProps) {
  const [expanded, setExpanded] = useState<ExpandedState>({})
  const activeRecords = useMemo(() => activeFleetRecords(records), [records])

  const columns = useMemo(
    () => [
      columnHelper.display({
        id: 'expander',
        header: '',
        cell: ({ row }) => {
          if (!row.getCanExpand()) {
            return null
          }
          const isExpanded = row.getIsExpanded()
          return (
            <button
              type="button"
              aria-expanded={isExpanded}
              aria-label={
                isExpanded
                  ? `Collapse build options for ${row.original.recordId}`
                  : `Expand build options for ${row.original.recordId}`
              }
              onClick={row.getToggleExpandedHandler()}
              className="inline-flex h-6 w-6 items-center justify-center rounded text-slate-400 hover:bg-black/15 hover:text-slate-200"
            >
              <ChevronDown
                className={cn(
                  'h-4 w-4 transition-transform duration-150',
                  !isExpanded && '-rotate-90'
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
      columnHelper.display({
        id: 'hull',
        header: 'Hull',
        cell: ({ row }) => (
          <FleetRecordHullCell
            hull={formatFleetHullDisplay(row.original, componentCatalog)}
          />
        ),
      }),
      columnHelper.accessor(
        (record) => formatFleetEngineDisplay(record, componentCatalog),
        {
          id: 'engine',
          header: 'Engine',
        }
      ),
      columnHelper.accessor((record) => formatFleetBeamsDisplay(record, componentCatalog), {
        id: 'beams',
        header: 'Beams',
      }),
      columnHelper.accessor(
        (record) => formatFleetLaunchersDisplay(record, componentCatalog),
        {
          id: 'launchers',
          header: 'Launchers',
        }
      ),
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
    [componentCatalog]
  )

  const table = useReactTable({
    data: activeRecords,
    columns,
    state: { expanded },
    onExpandedChange: setExpanded,
    getCoreRowModel: getCoreRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
    getRowCanExpand: (row) => alternateBuildOptionSets(row.original).length > 0,
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
              {table.getRowModel().rows.map((row) => (
                <Fragment key={row.id}>
                  <tr className="border-b border-[#52575d]/50">
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="px-3 py-2 text-gray-400">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                  {row.getIsExpanded() ? (
                    <tr className="border-b border-[#52575d]/50">
                      <td
                        colSpan={columns.length}
                        className="bg-black/10 px-3 py-2 text-xs text-slate-300"
                      >
                        <ul className="space-y-1">
                          {alternateBuildOptionSets(row.original).map((optionSet) => (
                            <li key={optionSet.comboId ?? optionSet.label}>
                              {formatBuildOptionSetComponentSummary(optionSet, componentCatalog)}
                            </li>
                          ))}
                        </ul>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
