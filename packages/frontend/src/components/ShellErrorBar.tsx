import { X } from 'lucide-react'
import { cn } from '../lib/utils'

export type ShellErrorItem = {
  id: string
  message: string
}

type ShellErrorBarProps = {
  errors: ShellErrorItem[]
  onDismiss: (id: string) => void
}

export function ShellErrorBar({ errors, onDismiss }: ShellErrorBarProps) {
  if (errors.length === 0) {
    return null
  }

  return (
    <div
      role="alert"
      aria-live="polite"
      className="w-full shrink-0 border-b border-red-900/70 bg-[#2a1518]"
    >
      <ul className="m-0 flex w-full list-none flex-col divide-y divide-red-950/80 p-0">
        {errors.map((item) => (
          <li
            key={item.id}
            className={cn(
              'flex w-full items-start gap-2 px-3 py-2.5',
              'text-sm leading-snug text-red-100'
            )}
          >
            <span className="min-w-0 flex-1 break-words">{item.message}</span>
            <button
              type="button"
              onClick={() => onDismiss(item.id)}
              className={cn(
                'shrink-0 rounded p-0.5 text-red-300/90',
                'hover:bg-red-950/60 hover:text-red-100',
                'focus:outline-none focus:ring-1 focus:ring-red-400/70'
              )}
              aria-label="Dismiss error"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
