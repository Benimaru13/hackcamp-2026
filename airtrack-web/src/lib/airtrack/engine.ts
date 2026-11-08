/**
 * The interaction engine: landmarks in, cursor + clicks out. No DOM, no camera,
 * no React — which is exactly why the behaviour can be unit tested.
 *
 * State machine (same contract the Python prototype settled on):
 *
 *        hold open palm 600 ms              hold fist 400 ms
 *   ARMED ------------------> ACTIVE ------------------> ARMED
 *     ^                        |
 *     +------ hand gone 2.5 s -+
 *
 * ARMED never touches the cursor. ACTIVE maps the fingertip through the
 * calibrated box, grows the cursor with distance, and turns a dwell (or a
 * pinch) into one click.
 */

import { normalizeProfile, type CalibrationProfile } from './calibration'
import { JitterMeter, OneEuroFilter } from './filter'
import {
  clamp,
  cursorRadiusPx,
  distanceFeet as feetFromRatio,
  distanceRatio,
  dist,
  handScale,
  mapToScreen,
  mirrorPoint,
  pinchGap,
  scaleBounds,
} from './geometry'
import { classifyPose } from './pose'
import type { ControlState, JitterLevel, Landmark, Pose, Vec2 } from './types'
import { LM } from './types'

const ARM_HOLD_MS = 600
const STOP_HOLD_MS = 400
const LOST_HAND_MS = 2500
const PINCH_CONTEXT_MS = 600
const CLICK_COOLDOWN_MS = 450

export interface AirViewport {
  width: number
  height: number
}

export interface AirState {
  handDetected: boolean
  pose: Pose
  state: ControlState
  cursor: { x: number; y: number; radius: number } | null
  /** 0..1 progress toward a dwell click, plus where it will land. */
  dwell: { progress: number; x: number; y: number } | null
  click: { x: number; y: number; kind: 'pinch' | 'dwell' } | null
  /** Pixels the page should scroll this frame (positive = down). */
  scroll: number
  distanceRatio: number
  distanceFeet: number
  jitter: { rms: number; score: number; level: JitterLevel }
  /** 0..1 while the arm gesture is being held. */
  armProgress: number
  hint: string
  activated: boolean
  released: boolean
}

/** Fast to enter, slow to leave, optional hold time — tolerates dropped frames. */
class Gate {
  private on = false
  private roseFlag = false
  private nOn = 0
  private nOff = 0
  private t0 = Number.NEGATIVE_INFINITY

  constructor(
    private enterFrames = 3,
    private exitFrames = 4,
  ) {}

  get open(): boolean {
    return this.on
  }

  /** True only on the frame the gate opens. */
  get rose(): boolean {
    return this.roseFlag
  }

  update(nowMs: number, active: boolean, holdMs = 0): boolean {
    this.roseFlag = false
    if (active) {
      this.nOff = 0
      if (this.nOn === 0) this.t0 = nowMs
      this.nOn += 1
      if (!this.on && this.nOn >= this.enterFrames && nowMs - this.t0 >= holdMs) {
        this.on = true
        this.roseFlag = true
      }
    } else {
      this.nOn = 0
      this.nOff += 1
      if (this.on && this.nOff >= this.exitFrames) this.on = false
    }
    return this.on
  }

  holdFraction(nowMs: number, holdMs: number): number {
    if (!this.on && this.nOn >= Math.max(this.enterFrames, 1) && holdMs > 0) {
      return clamp((nowMs - this.t0) / holdMs, 0, 1)
    }
    return 0
  }

  reset(): void {
    this.on = false
    this.roseFlag = false
    this.nOn = 0
    this.nOff = 0
    this.t0 = Number.NEGATIVE_INFINITY
  }
}

export class AirEngine {
  private profile: CalibrationProfile
  private viewport: AirViewport
  private readonly mirror: boolean

  state: ControlState = 'armed'

  private filterX = new OneEuroFilter()
  private filterY = new OneEuroFilter()
  private readonly jitterMeter = new JitterMeter()

  private pos: Vec2
  private hasPosition = false
  private lastSeenMs = Number.NEGATIVE_INFINITY
  private lastPointMs = Number.NEGATIVE_INFINITY
  private lastClickMs = Number.NEGATIVE_INFINITY

  private palmGate = new Gate()
  private fistGate = new Gate()
  private pinchGate = new Gate()

  private dwellAnchor: Vec2 | null = null
  private dwellStartMs = 0
  private dwellLocked = false
  private dwellProgress = 0

  private armProgress = 0
  private scrollPrevY: number | null = null
  private lastJitter = { rms: 0, score: 100, level: 'smooth' as JitterLevel }

  constructor(profile: CalibrationProfile, viewport: AirViewport, mirror = true) {
    this.profile = normalizeProfile(profile)
    this.viewport = viewport
    this.mirror = mirror
    this.pos = { x: viewport.width / 2, y: viewport.height / 2 }
  }

  setProfile(profile: CalibrationProfile): void {
    this.profile = normalizeProfile(profile)
    this.resetSmoothing()
  }

  setViewport(viewport: AirViewport): void {
    this.viewport = viewport
  }

  /** Safety stop: release control without touching the cursor. */
  disarm(): void {
    this.state = 'armed'
    this.palmGate.reset()
    this.fistGate.reset()
    this.pinchGate.reset()
    this.dwellAnchor = null
    this.dwellProgress = 0
    this.scrollPrevY = null
    this.resetSmoothing()
  }

  /** Explicit take-control (the Arm button, and the end of calibration). */
  arm(nowMs = 0): void {
    this.state = 'active'
    this.resetSmoothing()
    this.hasPosition = false
    this.lastSeenMs = nowMs
    this.dwellAnchor = null
  }

  reset(): void {
    this.disarm()
    this.hasPosition = false
    this.jitterMeter.reset()
    this.lastJitter = { rms: 0, score: 100, level: 'smooth' }
  }

  private resetSmoothing(): void {
    this.filterX.reset()
    this.filterY.reset()
  }

  private activate(nowMs: number, landmarks: Landmark[]): void {
    this.state = 'active'
    this.resetSmoothing()
    this.hasPosition = true
    this.pos = this.mapPoint(landmarks, this.radius(landmarks))
    this.lastSeenMs = nowMs
    this.dwellAnchor = null
    this.dwellProgress = 0
  }

  private radius(lm: Landmark[]): number {
    const ratio = distanceRatio(handScale(lm), this.profile.referenceSpan)
    return cursorRadiusPx(this.profile.cursor.basePx, ratio, this.profile.cursor.maxScale)
  }

  private bounds() {
    return scaleBounds(this.profile.bounds, this.profile.sensitivity)
  }

  private mapPoint(lm: Landmark[], radiusPx: number): Vec2 {
    const raw = mirrorPoint({ x: lm[LM.INDEX_TIP].x, y: lm[LM.INDEX_TIP].y }, this.mirror)
    return mapToScreen(raw, this.bounds(), this.viewport, radiusPx + 8)
  }

  /** Call once per frame. `nowMs` must be monotonic (rAF's timestamp is fine). */
  update(landmarks: Landmark[] | null, nowMs: number): AirState {
    const lm = landmarks && landmarks.length >= 21 ? landmarks : null
    const hasHand = !!lm && handScale(lm) > 1e-4
    const pose = hasHand ? classifyPose(lm, this.profile.pinchRatio) : 'none'
    const ratio = hasHand && lm ? distanceRatio(handScale(lm), this.profile.referenceSpan) : 1
    const radius = hasHand && lm ? this.radius(lm) : this.profile.cursor.basePx

    let activated = false
    let released = false
    let click: AirState['click'] = null
    let scroll = 0

    if (hasHand && lm) this.lastSeenMs = nowMs

    this.palmGate.update(nowMs, pose === 'palm', ARM_HOLD_MS)
    this.fistGate.update(nowMs, pose === 'fist', STOP_HOLD_MS)
    this.pinchGate.update(nowMs, pose === 'pinch')

    // ---------------------------------------------------------------- ARMED
    this.armProgress = pose === 'palm' ? this.palmGate.holdFraction(nowMs, ARM_HOLD_MS) : 0
    if (this.state === 'armed' && this.palmGate.rose && lm) {
      this.activate(nowMs, lm)
      activated = true
    }

    // --------------------------------------------------------------- ACTIVE
    if (this.state === 'active') {
      if (this.fistGate.rose) {
        this.disarm()
        released = true
      } else if (!hasHand && nowMs - this.lastSeenMs > LOST_HAND_MS) {
        this.disarm()
        released = true
      }
    }

    const active = this.state === 'active' && hasHand && !!lm
    const clickMode = this.profile.click.mode
    const pinching = active && pose === 'pinch'

    if (active && lm) {
      const freeze = pinching
      const rawPoint = mirrorPoint({ x: lm[LM.INDEX_TIP].x, y: lm[LM.INDEX_TIP].y }, this.mirror)

      // Distance-adaptive smoothing: farther away = smaller signal = more
      // smoothing, so the same filter feels identical at 1 m and 3 m.
      this.filterX.minCutoff = this.profile.smoothing.minCutoff / Math.sqrt(ratio)
      this.filterY.minCutoff = this.profile.smoothing.minCutoff / Math.sqrt(ratio)
      this.filterX.beta = this.profile.smoothing.beta
      this.filterY.beta = this.profile.smoothing.beta

      const timeSec = nowMs / 1000
      const smoothX = this.filterX.filter(rawPoint.x, timeSec)
      const smoothY = this.filterY.filter(rawPoint.y, timeSec)
      const target = mapToScreen(
        { x: smoothX, y: smoothY },
        this.bounds(),
        this.viewport,
        radius + 8,
      )

      const speedPx = Math.hypot(
        this.filterX.velocity * this.viewport.width,
        this.filterY.velocity * this.viewport.height,
      )

      if (!this.hasPosition) {
        this.pos = target
        this.hasPosition = true
      } else if (!freeze && pose === 'point') {
        const moved = dist(target, this.pos)
        const deliberate = speedPx >= this.profile.smoothing.minSpeedPxPerSec
        if (deliberate && moved >= this.profile.smoothing.deadzonePx) {
          this.pos = target
        }
      }

      // Jitter is measured on the *raw* mapped point while the hand is still,
      // so the score describes the camera and the user, not the filter.
      if (speedPx < this.profile.smoothing.minSpeedPxPerSec) {
        this.jitterMeter.push(
          mapToScreen(rawPoint, this.bounds(), this.viewport, radius + 8),
        )
      }
      this.lastJitter = {
        rms: this.jitterMeter.rms,
        score: this.jitterMeter.score,
        level: this.jitterMeter.level,
      }

      if (clickMode === 'pinch') {
        if (pose === 'point') this.lastPointMs = nowMs
        if (
          this.pinchGate.rose &&
          nowMs - this.lastPointMs < PINCH_CONTEXT_MS &&
          nowMs - this.lastClickMs > CLICK_COOLDOWN_MS
        ) {
          click = { x: this.pos.x, y: this.pos.y, kind: 'pinch' }
          this.lastClickMs = nowMs
        }
      }

      if (clickMode === 'dwell' && pose === 'point' && !freeze) {
        const tolerance = this.profile.click.dwellTolerancePx
        if (!this.dwellAnchor || dist(this.pos, this.dwellAnchor) > tolerance) {
          this.dwellAnchor = { ...this.pos }
          this.dwellStartMs = nowMs
          this.dwellLocked = false
        }
        const dwellMs = this.profile.click.dwellSeconds * 1000
        if (!this.dwellLocked && nowMs - this.dwellStartMs >= dwellMs) {
          click = { x: this.pos.x, y: this.pos.y, kind: 'dwell' }
          this.dwellLocked = true
          this.lastClickMs = nowMs
        }
        this.dwellProgress = this.dwellLocked
          ? 0
          : clamp((nowMs - this.dwellStartMs) / dwellMs, 0, 1)
      } else {
        this.dwellAnchor = null
        this.dwellProgress = 0
      }

      if (pose === 'two') {
        const y = lm[LM.MIDDLE_TIP].y
        if (this.scrollPrevY !== null) {
          scroll = (this.scrollPrevY - y) * this.viewport.height * 1.6
        }
        this.scrollPrevY = y
      } else {
        this.scrollPrevY = null
      }
    } else {
      this.dwellAnchor = null
      this.dwellProgress = 0
      this.scrollPrevY = null
      if (this.state === 'armed') this.hasPosition = false
    }

    const cursor =
      this.state === 'active' && hasHand
        ? { x: this.pos.x, y: this.pos.y, radius }
        : null

    return {
      handDetected: hasHand,
      pose,
      state: this.state,
      cursor,
      dwell:
        cursor && clickMode === 'dwell' && this.dwellProgress > 0
          ? { progress: this.dwellProgress, x: this.pos.x, y: this.pos.y }
          : null,
      click,
      scroll,
      distanceRatio: ratio,
      distanceFeet: feetFromRatio(ratio, this.profile.referenceDistanceFt),
      jitter: this.lastJitter,
      armProgress: this.armProgress,
      hint: this.hint(pose, active, clickMode),
      activated,
      released,
    }
  }

  private hint(pose: Pose, active: boolean, clickMode: 'dwell' | 'pinch'): string {
    if (this.state === 'armed') {
      if (pose === 'palm') return 'keep holding the palm…'
      if (pose === 'pinch') return 'a pinch never arms — open your hand flat'
      return 'hold an open palm to take control'
    }
    if (!active) return 'hand lost — return it to the frame'
    if (pose === 'fist') return 'fist releases control'
    if (pose === 'two') return 'two fingers: scroll'
    if (clickMode === 'pinch') return 'point to move, pinch to click'
    return 'point to move, hold still to click'
  }

  /** Live pinch feedback for the HUD (0 = open, 1 = fully pinched). */
  pinchProgress(landmarks: Landmark[] | null): number {
    if (!landmarks || landmarks.length < 21) return 0
    const gap = pinchGap(landmarks)
    if (!Number.isFinite(gap)) return 0
    return clamp(1 - gap / this.profile.pinchRatio, 0, 1)
  }
}
