import type {
  StellarCartographyOverlayPaneShapes,
  StellarCartographyOverlayRadialGradient,
} from '../../lib/cartography/stellarCartographyOverlay'
import type { BlackHolePaneShape } from '../../lib/cartography/blackHoleOverlay'
import {
  BLACK_HOLE_HALO_CYAN,
  BLACK_HOLE_HALO_CYAN_OPACITY,
  BLACK_HOLE_HALO_OUTER,
  BLACK_HOLE_HALO_OUTER_OPACITY,
} from '../../lib/cartography/stellarCartographyTheme'
import {
  ionStormCloudPaneShapeToRasterField,
  nebulaCloudPaneShapeToRasterField,
} from '../../lib/cartography/cartographyRasterFieldOverlay'
import { neutronClusterFluxPaneShapeToRasterField } from '../../lib/cartography/neutronClusterFluxOverlay'
import { RasterFieldOverlay } from '../RasterFieldOverlay'

function StellarCartographyRadialGradientDef({
  gradient,
  variant,
}: {
  gradient: StellarCartographyOverlayRadialGradient
  variant: 'core' | 'band'
}) {
  const innerStop = `${gradient.innerOffset * 100}%`
  if (variant === 'core') {
    return (
      <radialGradient id={gradient.id} cx="50%" cy="50%" r="50%">
        <stop offset="0%" stopColor={gradient.color} stopOpacity={gradient.peakOpacity} />
        <stop offset={innerStop} stopColor={gradient.color} stopOpacity={gradient.peakOpacity} />
        <stop offset="100%" stopColor={gradient.color} stopOpacity={gradient.edgeOpacity} />
      </radialGradient>
    )
  }
  return (
    <radialGradient id={gradient.id} cx="50%" cy="50%" r="50%">
      <stop offset="0%" stopColor={gradient.color} stopOpacity={0} />
      <stop offset={innerStop} stopColor={gradient.color} stopOpacity={0} />
      <stop offset={innerStop} stopColor={gradient.color} stopOpacity={gradient.peakOpacity} />
      <stop offset="100%" stopColor={gradient.color} stopOpacity={gradient.edgeOpacity} />
    </radialGradient>
  )
}

function BlackHoleErgosphereGradientDef({ shape }: { shape: BlackHolePaneShape }) {
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

function BlackHoleHaloGradientDef({ shape }: { shape: BlackHolePaneShape }) {
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

function BlackHoleOverlay({ shape }: { shape: BlackHolePaneShape }) {
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

function GradientAnnulusOverlay({
  cx,
  cy,
  coreR,
  bandR,
  coreFill,
  coreStroke,
  coreGradient,
  bandFill,
  bandStroke,
  strokeWidth,
  bandGradient,
}: {
  cx: number
  cy: number
  coreR: number
  bandR: number
  coreFill: string
  coreStroke?: string
  coreGradient?: StellarCartographyOverlayRadialGradient
  bandFill: string
  bandStroke: string
  strokeWidth: number
  bandGradient?: StellarCartographyOverlayRadialGradient
}) {
  return (
    <g>
      {(bandGradient != null || coreGradient != null) && (
        <defs>
          {bandGradient != null && (
            <StellarCartographyRadialGradientDef gradient={bandGradient} variant="band" />
          )}
          {coreGradient != null && (
            <StellarCartographyRadialGradientDef gradient={coreGradient} variant="core" />
          )}
        </defs>
      )}
      <circle
        cx={cx}
        cy={cy}
        r={bandR}
        fill={bandGradient != null ? `url(#${bandGradient.id})` : bandFill}
        stroke={bandStroke}
        strokeWidth={strokeWidth}
      />
      <circle
        cx={cx}
        cy={cy}
        r={coreR}
        fill={coreGradient != null ? `url(#${coreGradient.id})` : coreFill}
        stroke={coreStroke ?? 'none'}
        strokeWidth={coreStroke != null ? strokeWidth : 0}
      />
    </g>
  )
}

export function StellarCartographyVectorOverlay({
  shapes,
  width,
  height,
}: {
  shapes: Pick<
    StellarCartographyOverlayPaneShapes,
    | 'nebulaClouds'
    | 'ionStormClouds'
    | 'neutronFluxClouds'
    | 'circles'
    | 'blackHoles'
    | 'annuli'
    | 'debrisDiskBorders'
    | 'arrows'
  >
  width: number
  height: number
}) {
  return (
    <svg className="h-full w-full" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      {shapes.nebulaClouds.map((shape) => (
        <RasterFieldOverlay key={shape.key} {...nebulaCloudPaneShapeToRasterField(shape)} />
      ))}
      {shapes.ionStormClouds.map((shape) => (
        <RasterFieldOverlay key={shape.key} {...ionStormCloudPaneShapeToRasterField(shape)} />
      ))}
      {shapes.neutronFluxClouds.map((shape) => (
        <RasterFieldOverlay key={shape.key} {...neutronClusterFluxPaneShapeToRasterField(shape)} />
      ))}
      {shapes.circles.map(({ key, cx, cy, r, fill, stroke, strokeWidth, fillGradient }) => (
        <g key={key}>
          {fillGradient != null && (
            <defs>
              <StellarCartographyRadialGradientDef gradient={fillGradient} variant="core" />
            </defs>
          )}
          <circle
            cx={cx}
            cy={cy}
            r={r}
            fill={fillGradient != null ? `url(#${fillGradient.id})` : fill}
            stroke={stroke}
            strokeWidth={strokeWidth}
          />
        </g>
      ))}
      {shapes.blackHoles.map((shape) => (
        <BlackHoleOverlay key={shape.key} shape={shape} />
      ))}
      {shapes.annuli.map(({ key, ...annulus }) => (
        <GradientAnnulusOverlay key={key} {...annulus} />
      ))}
      {shapes.debrisDiskBorders.map(({ key, cx, cy, r, fill, stroke, strokeWidth }) => (
        <circle
          key={key}
          cx={cx}
          cy={cy}
          r={r}
          fill={fill}
          stroke={stroke}
          strokeWidth={strokeWidth}
        />
      ))}
      {shapes.arrows.map(({ key, x1, y1, x2, y2, stroke, strokeWidth }) => {
        const angle = Math.atan2(y2 - y1, x2 - x1)
        const headLen = 6
        const a1 = angle + Math.PI - Math.PI / 7
        const a2 = angle + Math.PI + Math.PI / 7
        const hx1 = x2 + headLen * Math.cos(a1)
        const hy1 = y2 + headLen * Math.sin(a1)
        const hx2 = x2 + headLen * Math.cos(a2)
        const hy2 = y2 + headLen * Math.sin(a2)
        return (
          <g key={key}>
            <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={stroke} strokeWidth={strokeWidth} />
            <polygon points={`${x2},${y2} ${hx1},${hy1} ${hx2},${hy2}`} fill={stroke} />
          </g>
        )
      })}
    </svg>
  )
}
