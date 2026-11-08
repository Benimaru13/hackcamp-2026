/**
 * Geometric primitives shared by calibration, the engine and the HUD.
 *
 * Everything is normalized to the frame (0..1), and every threshold is divided
 * by the hand's own size. That is what makes one set of numbers work at 1 m and
 * at 3 m: the hand is ~30 px wide at 3 m and ~130 px at 1 m, so raw pixel
 * thresholds would need retuning as soon as you step back.
 */

import type { Bounds, Landmark, Vec2 } from './types'
import { LM } from './types'

export function clamp(value: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, value))
}

export function dist(a: Vec2, b: Vec2): number {
  return Math.hypot(a.x - b.x, a.y - b.y)
}

/** Wrist → middle knuckle, about 9 cm on an adult hand. Shrinks with distance. */
export function handScale(lm: Landmark[]): number {
  if (lm.length < 21) return 0
  return Math.max(dist(lm[LM.WRIST], lm[LM.MIDDLE_MCP]), 1e-4)
}

/** Thumb-tip to index-tip gap in hand-units: ~0 pinched, >1.5 for a flat palm. */
export function pinchGap(lm: Landmark[]): number {
  const scale = handScale(lm)
  if (scale <= 0) return Number.POSITIVE_INFINITY
  return dist(lm[LM.THUMB_TIP], lm[LM.INDEX_TIP]) / scale
}

/** Center of the palm, used to keep the crop and overlays stable. */
export function handCenter(lm: Landmark[]): Vec2 {
  return {
    x: (lm[LM.WRIST].x + lm[LM.MIDDLE_MCP].x) / 2,
    y: (lm[LM.WRIST].y + lm[LM.MIDDLE_MCP].y) / 2,
  }
}

/**
 * How much farther the hand is than during calibration.
 * 1 = calibrated distance, 2 = twice as far (hand appears half as wide).
 */
export function distanceRatio(span: number, referenceSpan: number): number {
  if (span <= 1e-4 || referenceSpan <= 1e-4) return 1
  return clamp(referenceSpan / span, 0.4, 3.5)
}

export function distanceFeet(ratio: number, referenceFeet: number): number {
  return ratio * referenceFeet
}

/**
 * The cursor grows with distance so it stays visible and easy to aim at.
 * Sub-linear on purpose: at 3x the distance the ring is ~2.4x, not 3x.
 */
export function cursorRadiusPx(basePx: number, ratio: number, maxScale: number): number {
  const scale = clamp(Math.pow(ratio, 0.85), 0.85, Math.max(0.85, maxScale))
  return Math.round(basePx * scale * 10) / 10
}

/** Map a normalized frame point into viewport pixels through the calibrated box. */
export function mapToScreen(
  point: Vec2,
  bounds: Bounds,
  viewport: { width: number; height: number },
  marginPx = 0,
): Vec2 {
  const width = Math.max(bounds.maxX - bounds.minX, 1e-3)
  const height = Math.max(bounds.maxY - bounds.minY, 1e-3)
  const u = clamp((point.x - bounds.minX) / width, 0, 1)
  const v = clamp((point.y - bounds.minY) / height, 0, 1)
  const mx = Math.min(marginPx, viewport.width / 3)
  const my = Math.min(marginPx, viewport.height / 3)
  return {
    x: mx + u * Math.max(viewport.width - mx * 2, 1),
    y: my + v * Math.max(viewport.height - my * 2, 1),
  }
}

/** The preview is mirrored; this keeps the overlay, cursor and HUD in agreement. */
export function mirrorPoint(point: Vec2, mirror: boolean): Vec2 {
  return mirror ? { x: 1 - point.x, y: point.y } : { x: point.x, y: point.y }
}

/** Shrink or grow the calibrated box around its center (sensitivity control). */
export function scaleBounds(bounds: Bounds, sensitivity: number): Bounds {
  const s = clamp(sensitivity, 0.4, 3)
  if (Math.abs(s - 1) < 1e-3) return bounds
  const cx = (bounds.minX + bounds.maxX) / 2
  const cy = (bounds.minY + bounds.maxY) / 2
  const hw = ((bounds.maxX - bounds.minX) / 2) / s
  const hh = ((bounds.maxY - bounds.minY) / 2) / s
  return {
    minX: clamp(cx - hw, -0.2, 1.2),
    maxX: clamp(cx + hw, -0.2, 1.2),
    minY: clamp(cy - hh, -0.2, 1.2),
    maxY: clamp(cy + hh, -0.2, 1.2),
  }
}
