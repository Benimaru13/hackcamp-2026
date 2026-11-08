/**
 * Smoothing and jitter measurement.
 *
 * One Euro filter (Casiez, Roussel, Vogel 2012): heavy smoothing while the hand
 * is still, light smoothing while it moves, so the cursor does not shake and
 * does not lag behind a deliberate swipe.
 *
 * The jitter meter measures the *raw* signal's second difference — deviation
 * from constant velocity. That is a property of the camera and the user's hand,
 * not of the filter, so it can drive auto-tuning and the 0-100 score honestly.
 */

import { clamp } from './geometry'
import type { JitterLevel, Vec2 } from './types'

function alpha(cutoff: number, dt: number): number {
  const tau = 1 / (2 * Math.PI * Math.max(cutoff, 1e-3))
  return 1 / (1 + tau / Math.max(dt, 1e-4))
}

export class OneEuroFilter {
  private tPrev: number | null = null
  private xPrev = 0
  private dxPrev = 0
  private xHat = 0
  private vHat = 0

  constructor(
    public minCutoff = 1.0,
    public beta = 0.5,
    public dCutoff = 1.0,
  ) {}

  reset(): void {
    this.tPrev = null
    this.xPrev = 0
    this.dxPrev = 0
    this.xHat = 0
    this.vHat = 0
  }

  /** Smoothed velocity in units per second. */
  get velocity(): number {
    return this.vHat
  }

  filter(value: number, timeSec: number): number {
    if (this.tPrev === null) {
      this.tPrev = timeSec
      this.xPrev = value
      this.xHat = value
      return value
    }
    const dt = Math.max(timeSec - this.tPrev, 1e-3)
    const dx = (value - this.xPrev) / dt
    const aD = alpha(this.dCutoff, dt)
    const dxHat = aD * dx + (1 - aD) * this.dxPrev
    const cutoff = this.minCutoff + this.beta * Math.abs(dxHat)
    const a = alpha(cutoff, dt)
    this.xHat = a * value + (1 - a) * this.xPrev
    this.xPrev = this.xHat
    this.dxPrev = dxHat
    this.tPrev = timeSec
    this.vHat = dxHat
    return this.xHat
  }
}

/** Running RMS of frame-to-frame acceleration, in screen pixels. */
export class JitterMeter {
  private ema = 0
  private prevPos: Vec2 | null = null
  private prevDelta: Vec2 | null = null
  private sampleCount = 0

  reset(): void {
    this.ema = 0
    this.prevPos = null
    this.prevDelta = null
    this.sampleCount = 0
  }

  /** Add one raw cursor position (pixels). Call once per frame while still. */
  push(point: Vec2): void {
    if (this.prevPos) {
      const delta = { x: point.x - this.prevPos.x, y: point.y - this.prevPos.y }
      if (this.prevDelta) {
        const residual = Math.hypot(delta.x - this.prevDelta.x, delta.y - this.prevDelta.y) / 2
        const square = residual * residual
        this.ema = this.sampleCount === 0 ? square : this.ema * 0.9 + square * 0.1
        this.sampleCount += 1
      }
      this.prevDelta = delta
    }
    this.prevPos = { x: point.x, y: point.y }
  }

  get samples(): number {
    return this.sampleCount
  }

  /** RMS jitter in pixels (0 when nothing measured). */
  get rms(): number {
    return this.sampleCount === 0 ? 0 : Math.sqrt(this.ema)
  }

  /** 0-100: 100 = rock steady. */
  get score(): number {
    return Math.round(clamp(100 * Math.exp(-this.rms / 6), 0, 100))
  }

  get level(): JitterLevel {
    if (this.sampleCount === 0) return 'smooth'
    if (this.rms < 1.2) return 'smooth'
    if (this.rms < 3) return 'steady'
    if (this.rms < 7) return 'shaky'
    return 'very shaky'
  }
}

export interface TunedSmoothing {
  minCutoff: number
  beta: number
  deadzonePx: number
  minSpeedPxPerSec: number
  dwellTolerancePx: number
}

/**
 * Turn a measured jitter level into settings.
 * Shaky hands get more smoothing and a larger deadzone; steady hands keep
 * responsiveness (smoothing everything equally would make a good camera feel
 * laggy for no reason).
 */
export function tuneFromJitter(rmsPx: number): TunedSmoothing {
  const rms = clamp(rmsPx, 0, 30)
  return {
    minCutoff: round(1.6 - rms * 0.18, 0.45, 1.6),
    beta: round(0.25 + rms * 0.06, 0.25, 0.9),
    deadzonePx: round(2 + rms * 1.2, 2, 18),
    minSpeedPxPerSec: round(40 + rms * 30, 40, 320),
    dwellTolerancePx: round(8 + rms * 2, 8, 40),
  }
}

function round(value: number, lo: number, hi: number): number {
  return Math.round(clamp(value, lo, hi) * 100) / 100
}
