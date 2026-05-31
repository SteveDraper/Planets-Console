import type { BlackHolePaneShape } from '../../lib/cartography/blackHoleOverlay'
import {
  BLACK_HOLE_HALO_CYAN,
  BLACK_HOLE_HALO_CYAN_OPACITY,
  BLACK_HOLE_HALO_OUTER,
  BLACK_HOLE_HALO_OUTER_OPACITY,
} from '../../lib/cartography/stellarCartographyTheme'

export function BlackHoleErgosphereGradientDef({ shape }: { shape: BlackHolePaneShape }) {
  return (
    <radialGradient id={shape.ergosphereGradientId} cx="50%" cy="50%" r="50%">
      {shape.ergosphereStops.map((stop, index) => (
        <stop
          key={`${shape.key}-stop-${index}`}
          offset={`${stop.offset * 100}%`}
          stopColor={stop.color}
          stopOpacity={stop.opacity}
        />
      ))}
    </radialGradient>
  )
}

export function BlackHoleHaloGradientDef({ shape }: { shape: BlackHolePaneShape }) {
  const edgeStop = `${shape.ergosphereEdgeOffset * 100}%`
  const gradientId = `${shape.key}-halo-grad`
  return (
    <radialGradient id={gradientId} cx="50%" cy="50%" r="50%">
      <stop offset="0%" stopColor="#000000" stopOpacity={0} />
      <stop offset={edgeStop} stopColor="#000000" stopOpacity={0} />
      <stop offset={edgeStop} stopColor={BLACK_HOLE_HALO_CYAN} stopOpacity={BLACK_HOLE_HALO_CYAN_OPACITY} />
      <stop
        offset="100%"
        stopColor={BLACK_HOLE_HALO_OUTER}
        stopOpacity={BLACK_HOLE_HALO_OUTER_OPACITY}
      />
    </radialGradient>
  )
}

export function BlackHoleOverlay({ shape }: { shape: BlackHolePaneShape }) {
  const haloGradientId = `${shape.key}-halo-grad`
  return (
    <g>
      <defs>
        <BlackHoleHaloGradientDef shape={shape} />
        <BlackHoleErgosphereGradientDef shape={shape} />
      </defs>
      <circle
        cx={shape.cx}
        cy={shape.cy}
        r={shape.haloR}
        fill={`url(#${haloGradientId})`}
        stroke="none"
      />
      <circle
        cx={shape.cx}
        cy={shape.cy}
        r={shape.ergosphereR}
        fill={`url(#${shape.ergosphereGradientId})`}
        stroke="none"
      />
    </g>
  )
}
