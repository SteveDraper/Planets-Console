import {
  WORMHOLE_ENDPOINT_DISC_FILL,
  WORMHOLE_SPIRAL_BLUE,
  WORMHOLE_SPIRAL_ORANGE,
} from './cartography/stellarCartographyTheme'

/** Fills its container; container width/height set the map-scaled diameter in pane pixels. */
export function WormholeEndpointIconMark() {
  return (
    <svg viewBox="0 0 16 16" className="h-full w-full" aria-hidden opacity={0.82}>
      <circle cx="8" cy="8" r="8" fill={WORMHOLE_ENDPOINT_DISC_FILL} />
      <path
        d="M 8 3.1 C 12.1 3.4, 13.2 7.2, 11.4 10.6 C 9.9 13.2, 5.6 12.5, 4 9.1 C 2.9 7, 4.3 4.4, 6.9 3.7"
        fill="none"
        stroke={WORMHOLE_SPIRAL_BLUE}
        strokeWidth="2.4"
        strokeLinecap="round"
      />
      <path
        d="M 8 12.9 C 3.9 12.6, 2.8 8.8, 4.6 5.4 C 6.1 2.8, 10.4 3.5, 12 6.9 C 13.1 9, 11.7 11.6, 9.1 12.3"
        fill="none"
        stroke={WORMHOLE_SPIRAL_ORANGE}
        strokeWidth="2.4"
        strokeLinecap="round"
      />
      <circle cx="8" cy="8" r="2.3" fill="#0a0a0a" />
    </svg>
  )
}
