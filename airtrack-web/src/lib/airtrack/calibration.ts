/**
 * Calibration: what a profile is, how the reach box is measured, and how a
 * profile is derived from what the user actually did during the wizard.
 *
 * A profile is the difference between "some gesture code" and "this works for
 * me": the comfortable reach box, the hand size at your normal distance, your
 * pinch distance, and the smoothing that matches how steady your hand is.
 */

import { clamp, handScale } from './geometry'
import { tuneFromJitter } from './filter'
import type { Bounds, Landmark, Vec2 } from './types'

export type ClickMode = 'dwell' | 'pinch'

export interface CalibrationProfile {
  version: 1
  name: string
  createdAt: string
  /** Comfortable reach, normalized to the frame. */
  bounds: Bounds
  /** Hand scale (wrist → middle knuckle) at the distance you normally sit. */
  referenceSpan: number
  /** Your normal distance from the camera, only used for the feet readout. */
  referenceDistanceFt: number
  /** Thumb-index gap below which a pinch counts, in hand-units. */
  pinchRatio: number
  jitter: { rmsPx: number; score: number }
  smoothing: {
    minCutoff: number
    beta: number
    deadzonePx: number
    minSpeedPxPerSec: number
  }
  click: { mode: ClickMode; dwellSeconds: number; dwellTolerancePx: number }
  cursor: { basePx: number; maxScale: number }
  /** 1 = the calibrated box fills the screen exactly. */
  sensitivity: number
}

export const DEFAULT_PROFILE: CalibrationProfile = {
  version: 1,
  name: 'Default',
  createdAt: '',
  bounds: { minX: 0.2, maxX: 0.8, minY: 0.15, maxY: 0.82 },
  referenceSpan: 0.075,
  referenceDistanceFt: 3,
  pinchRatio: 0.38,
  jitter: { rmsPx: 0, score: 100 },
  smoothing: { minCutoff: 1.0, beta: 0.5, deadzonePx: 4, minSpeedPxPerSec: 80 },
  click: { mode: 'dwell', dwellSeconds: 1.2, dwellTolerancePx: 18 },
  cursor: { basePx: 18, maxScale: 2.4 },
  sensitivity: 1,
}

function percentile(sorted: number[], q: number): number {
  if (sorted.length === 0) return 0
  const pos = clamp(q, 0, 1) * (sorted.length - 1)
  const lo = Math.floor(pos)
  const hi = Math.ceil(pos)
  if (lo === hi) return sorted[lo]
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo)
}

/**
 * Reach box from the points the user swept through.
 * Trims 4% off each end so one tracking glitch cannot define the whole box,
 * then guarantees a usable minimum size.
 */
export function boundsFromSamples(points: Vec2[], trim = 0.04): Bounds {
  if (points.length < 8) return { ...DEFAULT_PROFILE.bounds }
  const xs = points.map((p) => p.x).sort((a, b) => a - b)
  const ys = points.map((p) => p.y).sort((a, b) => a - b)
  let minX = percentile(xs, trim)
  let maxX = percentile(xs, 1 - trim)
  let minY = percentile(ys, trim)
  let maxY = percentile(ys, 1 - trim)

  const minWidth = 0.12
  const minHeight = 0.12
  if (maxX - minX < minWidth) {
    const cx = (minX + maxX) / 2
    minX = cx - minWidth / 2
    maxX = cx + minWidth / 2
  }
  if (maxY - minY < minHeight) {
    const cy = (minY + maxY) / 2
    minY = cy - minHeight / 2
    maxY = cy + minHeight / 2
  }

  return {
    minX: clamp(minX, 0, 0.95),
    maxX: clamp(maxX, 0.05, 1),
    minY: clamp(minY, 0, 0.95),
    maxY: clamp(maxY, 0.05, 1),
  }
}

/**
 * Personal pinch threshold from what we saw during the pinch step.
 * Uses the gap between "clearly pinched" and "clearly open" rather than the
 * single smallest sample, so one noisy frame cannot make every open hand click.
 */
export function pinchThresholdFromSamples(pinched: number[], open: number[]): number {
  const tight = pinched.filter((g) => Number.isFinite(g) && g > 0)
  const loose = open.filter((g) => Number.isFinite(g) && g > 0)
  if (tight.length < 3 || loose.length < 3) return DEFAULT_PROFILE.pinchRatio
  const pinchedHigh = percentile([...tight].sort((a, b) => a - b), 0.9)
  const openLow = percentile([...loose].sort((a, b) => a - b), 0.1)
  if (!(openLow > pinchedHigh)) return DEFAULT_PROFILE.pinchRatio
  return Math.round(clamp((pinchedHigh + openLow) / 2, 0.2, 0.55) * 100) / 100
}

export interface BuildProfileInput {
  name?: string
  bounds: Bounds
  referenceSpan: number
  jitterRmsPx: number
  pinchRatio?: number
  referenceDistanceFt?: number
  base?: CalibrationProfile
}

/** Merge the measurements into a complete, saved profile. */
export function buildProfile(input: BuildProfileInput): CalibrationProfile {
  const base = input.base ?? DEFAULT_PROFILE
  const tuned = tuneFromJitter(input.jitterRmsPx)
  const score = Math.round(clamp(100 * Math.exp(-Math.max(input.jitterRmsPx, 0) / 6), 0, 100))
  return {
    ...base,
    version: 1,
    name: input.name?.trim() || base.name,
    createdAt: new Date().toISOString(),
    bounds: { ...input.bounds },
    referenceSpan: round(input.referenceSpan, 0.02, 0.35, 4),
    referenceDistanceFt: round(input.referenceDistanceFt ?? base.referenceDistanceFt, 1, 15, 1),
    pinchRatio: round(input.pinchRatio ?? base.pinchRatio, 0.2, 0.55, 2),
    jitter: { rmsPx: round(input.jitterRmsPx, 0, 40, 2), score },
    smoothing: {
      minCutoff: tuned.minCutoff,
      beta: tuned.beta,
      deadzonePx: tuned.deadzonePx,
      minSpeedPxPerSec: tuned.minSpeedPxPerSec,
    },
    click: {
      mode: base.click.mode,
      dwellSeconds: base.click.dwellSeconds,
      dwellTolerancePx: tuned.dwellTolerancePx,
    },
  }
}

function round(value: number, lo: number, hi: number, decimals: number): number {
  const f = 10 ** decimals
  return Math.round(clamp(value, lo, hi) * f) / f
}

/**
 * Anything read back from storage or DeepSpace goes through here: unknown or
 * old shapes must never crash the tracker, and out-of-range numbers must never
 * turn the cursor into a 400 px blob.
 */
export function normalizeProfile(raw: unknown): CalibrationProfile {
  const value = (raw ?? {}) as Partial<CalibrationProfile>
  const bounds = { ...DEFAULT_PROFILE.bounds, ...(value.bounds ?? {}) }
  const safeBounds: Bounds = {
    minX: clamp(Number(bounds.minX) || 0, 0, 0.95),
    maxX: clamp(Number(bounds.maxX) || 1, 0.05, 1),
    minY: clamp(Number(bounds.minY) || 0, 0, 0.95),
    maxY: clamp(Number(bounds.maxY) || 1, 0.05, 1),
  }
  if (safeBounds.maxX - safeBounds.minX < 0.05) {
    safeBounds.minX = DEFAULT_PROFILE.bounds.minX
    safeBounds.maxX = DEFAULT_PROFILE.bounds.maxX
  }
  if (safeBounds.maxY - safeBounds.minY < 0.05) {
    safeBounds.minY = DEFAULT_PROFILE.bounds.minY
    safeBounds.maxY = DEFAULT_PROFILE.bounds.maxY
  }

  const smoothing = { ...DEFAULT_PROFILE.smoothing, ...(value.smoothing ?? {}) }
  const click = { ...DEFAULT_PROFILE.click, ...(value.click ?? {}) }
  const cursor = { ...DEFAULT_PROFILE.cursor, ...(value.cursor ?? {}) }

  return {
    version: 1,
    name: typeof value.name === 'string' && value.name.trim() ? value.name.trim().slice(0, 60) : DEFAULT_PROFILE.name,
    createdAt: typeof value.createdAt === 'string' ? value.createdAt : '',
    bounds: safeBounds,
    referenceSpan: clamp(Number(value.referenceSpan) || DEFAULT_PROFILE.referenceSpan, 0.02, 0.35),
    referenceDistanceFt: clamp(Number(value.referenceDistanceFt) || DEFAULT_PROFILE.referenceDistanceFt, 1, 15),
    pinchRatio: clamp(Number(value.pinchRatio) || DEFAULT_PROFILE.pinchRatio, 0.2, 0.55),
    jitter: {
      rmsPx: clamp(Number(value.jitter?.rmsPx) || 0, 0, 60),
      score: clamp(Number(value.jitter?.score) || DEFAULT_PROFILE.jitter.score, 0, 100),
    },
    smoothing: {
      minCutoff: clamp(Number(smoothing.minCutoff) || DEFAULT_PROFILE.smoothing.minCutoff, 0.35, 2.5),
      beta: clamp(Number(smoothing.beta) || DEFAULT_PROFILE.smoothing.beta, 0.1, 1.5),
      deadzonePx: clamp(Number(smoothing.deadzonePx) || DEFAULT_PROFILE.smoothing.deadzonePx, 1, 24),
      minSpeedPxPerSec: clamp(
        Number(smoothing.minSpeedPxPerSec) || DEFAULT_PROFILE.smoothing.minSpeedPxPerSec,
        20,
        400,
      ),
    },
    click: {
      mode: click.mode === 'pinch' ? 'pinch' : 'dwell',
      dwellSeconds: clamp(Number(click.dwellSeconds) || DEFAULT_PROFILE.click.dwellSeconds, 0.5, 3),
      dwellTolerancePx: clamp(
        Number(click.dwellTolerancePx) || DEFAULT_PROFILE.click.dwellTolerancePx,
        6,
        48,
      ),
    },
    cursor: {
      basePx: clamp(Number(cursor.basePx) || DEFAULT_PROFILE.cursor.basePx, 8, 44),
      maxScale: clamp(Number(cursor.maxScale) || DEFAULT_PROFILE.cursor.maxScale, 1, 3.5),
    },
    sensitivity: clamp(Number(value.sensitivity) || 1, 0.5, 2),
  }
}

/** Convenience for the calibration wizard: reference span from captured hands. */
export function averageHandScale(samples: Landmark[][]): number {
  const spans = samples.filter((lm) => lm.length >= 21).map(handScale)
  if (spans.length === 0) return DEFAULT_PROFILE.referenceSpan
  const mean = spans.reduce((a, b) => a + b, 0) / spans.length
  return Math.round(clamp(mean, 0.02, 0.35) * 10000) / 10000
}
