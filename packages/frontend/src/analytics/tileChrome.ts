import { cn } from '../lib/utils'

export type TileChrome = {
  supportsMode: boolean
  depressed: boolean
}

export function tileClassName({ supportsMode, depressed }: TileChrome): string {
  return cn(
    'rounded border text-sm transition-shadow',
    supportsMode ? 'text-slate-200' : 'cursor-default opacity-50 text-slate-500',
    depressed
      ? 'border-t-[#2a2d30] border-l-[#2a2d30] border-b-[#5a5f65] border-r-[#5a5f65] bg-[#383c41] shadow-[inset_1px_1px_2px_0_rgba(0,0,0,0.3)]'
      : 'border-t-[#5a5f65] border-l-[#5a5f65] border-b-[#2a2d30] border-r-[#2a2d30] bg-[#464b51] shadow-[inset_1px_1px_0_0_rgba(255,255,255,0.06)]'
  )
}
