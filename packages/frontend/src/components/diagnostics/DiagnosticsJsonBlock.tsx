import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '../../lib/utils'

type CollapsibleJsonViewProps = {
  value: unknown
  defaultExpandedDepth?: number
  depth?: number
  label?: string
}

function jsonPreview(value: unknown): string {
  if (value === null) return 'null'
  if (typeof value === 'string') return JSON.stringify(value)
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return `Array(${value.length})`
  if (typeof value === 'object') return `Object(${Object.keys(value as object).length})`
  return String(value)
}

function isEmptyValue(value: unknown): boolean {
  if (value == null) return true
  if (Array.isArray(value)) return value.length === 0
  if (typeof value === 'object') return Object.keys(value as object).length === 0
  return false
}

export function CollapsibleJsonView({
  value,
  defaultExpandedDepth = 2,
  depth = 0,
  label,
}: CollapsibleJsonViewProps) {
  const [expanded, setExpanded] = useState(depth < defaultExpandedDepth)

  if (value === null || typeof value !== 'object') {
    return (
      <span className="font-mono text-[10px] text-slate-300">
        {label != null ? (
          <>
            <span className="text-slate-500">{label}: </span>
            {jsonPreview(value)}
          </>
        ) : (
          jsonPreview(value)
        )}
      </span>
    )
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <span className="font-mono text-[10px] text-slate-400">[]</span>
    }
    return (
      <div className="font-mono text-[10px] text-slate-300">
        <button
          type="button"
          onClick={() => setExpanded((current) => !current)}
          className={cn(
            'inline-flex items-center gap-1 rounded px-0.5 text-left text-slate-300',
            'hover:bg-white/5 focus:outline-none focus:ring-1 focus:ring-slate-500'
          )}
          aria-expanded={expanded}
        >
          <ChevronDown
            className={cn('h-3 w-3 shrink-0 text-slate-500', !expanded && '-rotate-90')}
            aria-hidden
          />
          <span>{label != null ? `${label}: ` : ''}[{value.length}]</span>
        </button>
        {expanded ? (
          <ul className="mt-1 space-y-1 border-l border-[#52575d]/70 pl-3">
            {value.map((item, index) => (
              <li key={index} className="min-w-0">
                <CollapsibleJsonView
                  value={item}
                  defaultExpandedDepth={defaultExpandedDepth}
                  depth={depth + 1}
                  label={String(index)}
                />
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    )
  }

  const entries = Object.entries(value as Record<string, unknown>)
  if (entries.length === 0) {
    return <span className="font-mono text-[10px] text-slate-400">{'{}'}</span>
  }

  return (
    <div className="font-mono text-[10px] text-slate-300">
      <button
        type="button"
        onClick={() => setExpanded((current) => !current)}
        className={cn(
          'inline-flex items-center gap-1 rounded px-0.5 text-left text-slate-300',
          'hover:bg-white/5 focus:outline-none focus:ring-1 focus:ring-slate-500'
        )}
        aria-expanded={expanded}
      >
        <ChevronDown
          className={cn('h-3 w-3 shrink-0 text-slate-500', !expanded && '-rotate-90')}
          aria-hidden
        />
        <span>
          {label != null ? `${label}: ` : ''}
          {'{'}
          {entries.length}
          {'}'}
        </span>
      </button>
      {expanded ? (
        <ul className="mt-1 space-y-1 border-l border-[#52575d]/70 pl-3">
          {entries.map(([entryKey, entryValue]) => (
            <li key={entryKey} className="min-w-0">
              <CollapsibleJsonView
                value={entryValue}
                defaultExpandedDepth={defaultExpandedDepth}
                depth={depth + 1}
                label={entryKey}
              />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

type DiagnosticsJsonBlockProps = {
  value: unknown
  maxHeightClassName?: string
  emptyLabel?: string
}

export function DiagnosticsJsonBlock({
  value,
  maxHeightClassName = 'max-h-96',
  emptyLabel = 'No data',
}: DiagnosticsJsonBlockProps) {
  if (isEmptyValue(value)) {
    return <p className="text-[10px] text-slate-500">{emptyLabel}</p>
  }
  return (
    <div className={`overflow-auto rounded border border-[#52575d]/50 bg-[#2a2d30]/70 p-2 ${maxHeightClassName}`}>
      <CollapsibleJsonView value={value} defaultExpandedDepth={2} />
    </div>
  )
}
