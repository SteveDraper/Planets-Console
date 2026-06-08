type InferenceStopIconProps = {
  className?: string
}

/** Prohibition-style stop: red ring with diagonal line. */
export function InferenceStopIcon({ className = 'h-3.5 w-3.5' }: InferenceStopIconProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={className}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
    >
      <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.5" />
      <line x1="4.5" y1="11.5" x2="11.5" y2="4.5" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  )
}
