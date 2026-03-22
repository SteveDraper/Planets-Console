import { useId, useState } from 'react'
import { cn } from '../lib/utils'

type MapPaneWithDisplayControlsProps = {
  children: React.ReactNode
  /** Future map display controls (layers, labels, etc.). */
  controls?: React.ReactNode
}

function UpTriangleIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 12 10"
      width={12}
      height={10}
      aria-hidden
    >
      <path d="M6 0 L12 10 L0 10 Z" fill="currentColor" />
    </svg>
  )
}

function DownTriangleIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 12 10"
      width={12}
      height={10}
      aria-hidden
    >
      <path d="M0 0 L12 0 L6 10 Z" fill="currentColor" />
    </svg>
  )
}

/**
 * Wraps the map: full-bleed React Flow keeps its size; a bottom sheet for display controls
 * overlays the map. When collapsed, the bottom edge is thickened only under the panel
 * width (right half) and a tab on the lower right hints that the sheet can be opened.
 */
export function MapPaneWithDisplayControls({
  children,
  controls,
}: MapPaneWithDisplayControlsProps) {
  const [isOpen, setIsOpen] = useState(false)
  const panelId = useId()

  return (
    <div className="relative min-h-0 min-w-0 flex-1 overflow-hidden border border-[#52575d] bg-black">
      {children}

      {!isOpen && (
        <div
          className="pointer-events-none absolute bottom-0 right-0 z-[40] h-[3px] w-1/2 bg-[#52575d]"
          style={{
            clipPath:
              'polygon(0% 100%, 3px 0, calc(100% - 3px) 0, 100% 100%)',
          }}
          aria-hidden
        />
      )}

      <div
        id={panelId}
        role="region"
        aria-label="Map options"
        aria-hidden={!isOpen}
        inert={!isOpen}
        className={cn(
          'absolute bottom-0 right-0 z-[50] flex max-h-full min-h-0 w-1/2 min-w-0 flex-col overflow-hidden',
          'rounded-tl-md border border-b-0 border-[#52575d] bg-[#40454a] shadow-lg',
          'transition-transform duration-200 ease-out',
          isOpen ? 'translate-y-0' : 'translate-y-full pointer-events-none'
        )}
      >
        <div className="flex shrink-0 items-center justify-between gap-2 border-b border-[#52575d] py-2 pl-3 pr-0">
          <h2 className="min-w-0 flex-1 text-sm font-medium text-slate-200">Map options</h2>
          <button
            type="button"
            className="pointer-events-auto shrink-0 translate-x-px rounded p-1.5 text-slate-300 hover:bg-[#4a4f54] hover:text-slate-100"
            aria-expanded={isOpen}
            aria-controls={panelId}
            onClick={() => setIsOpen(false)}
          >
            <span className="sr-only">Hide map options</span>
            <DownTriangleIcon className="text-slate-300" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-3 text-sm text-gray-400">
          {controls ?? (
            <p className="text-gray-500">Map options will go here.</p>
          )}
        </div>
      </div>

      <button
        type="button"
        className={cn(
          'absolute bottom-0 right-0 z-[60] flex items-end justify-center bg-transparent px-1.5 pb-0 pt-1.5 text-[#52575d]',
          'hover:opacity-80',
          'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#52575d]',
          isOpen && 'hidden'
        )}
        aria-expanded={isOpen}
        aria-controls={panelId}
        onClick={() => setIsOpen(true)}
      >
        <span className="sr-only">Show map options</span>
        <UpTriangleIcon />
      </button>
    </div>
  )
}
