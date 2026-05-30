import { cn } from '../../lib/utils'

type CartographyDisplayModeControlProps<T extends string> = {
  label: string
  ariaLabel: string
  modes: readonly T[]
  modeLabels: Record<T, string>
  value: T
  onChange: (mode: T) => void
}

export function CartographyDisplayModeControl<T extends string>({
  label,
  ariaLabel,
  modes,
  modeLabels,
  value,
  onChange,
}: CartographyDisplayModeControlProps<T>) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span>{label}</span>
      <div
        role="radiogroup"
        aria-label={ariaLabel}
        className="flex min-w-0 rounded border border-[#52575d] bg-slate-800/80 p-0.5"
      >
        {modes.map((mode) => {
          const selected = value === mode
          return (
            <button
              key={mode}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onChange(mode)}
              className={cn(
                'min-w-0 flex-1 rounded px-1.5 py-0.5 text-[11px] leading-tight transition-colors',
                selected
                  ? 'bg-slate-600 text-slate-100'
                  : 'text-slate-400 hover:bg-black/20 hover:text-slate-200'
              )}
            >
              {modeLabels[mode]}
            </button>
          )
        })}
      </div>
    </div>
  )
}
