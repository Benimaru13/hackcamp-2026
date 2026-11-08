/**
 * The on-screen pointer. Position, size and dwell progress are written to this
 * element's style directly by useAirPointer at frame rate — no React re-render
 * per frame — so the ring stays smooth.
 *
 * Size matters here: the ring is the distance cue. Far away it grows, so the
 * cursor stays visible and easy to aim at from across the room.
 */

import type { RefObject } from 'react'

export function AirCursor({ innerRef }: { innerRef: RefObject<HTMLDivElement | null> }) {
  return (
    <div
      ref={innerRef}
      data-state="armed"
      className="pointer-events-none fixed left-0 top-0 z-[60] hidden select-none"
    >
      <div className="absolute inset-0 rounded-full border-2 border-primary/80 shadow-[0_0_28px_rgba(129,140,248,0.5)]" />
      <div
        className="absolute inset-0 rounded-full opacity-90"
        style={{
          background:
            'conic-gradient(var(--color-primary) calc(var(--dwell, 0) * 360deg), rgba(129,140,248,0.08) 0)',
        }}
      />
      <div className="absolute left-1/2 top-1/2 size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary" />
    </div>
  )
}
