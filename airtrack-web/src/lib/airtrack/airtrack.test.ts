/**
 * Unit tests for the AirTrack logic. No camera, no DOM: synthetic landmarks in,
 * cursor/click behaviour out. This is the part that has to be right before a
 * real webcam is anywhere near it.
 */

import { describe, expect, it } from 'vitest'
import {
  DEFAULT_PROFILE,
  boundsFromSamples,
  buildProfile,
  normalizeProfile,
  pinchThresholdFromSamples,
} from './calibration'
import { AirEngine } from './engine'
import { JitterMeter, tuneFromJitter } from './filter'
import { cursorRadiusPx, distanceRatio, handScale, mapToScreen } from './geometry'
import { classifyPose } from './pose'
import { SimHand, spanForDistance } from './simulate'

const VIEWPORT = { width: 1440, height: 900 }
type SimPose = 'point' | 'palm' | 'fist' | 'pinch' | 'two'

function poseAt(pose: SimPose, feet = 3): string {
  const hand = new SimHand({ pose, span: spanForDistance(feet) }).landmarks()
  return classifyPose(hand, DEFAULT_PROFILE.pinchRatio)
}

function rig(profile = DEFAULT_PROFILE) {
  const engine = new AirEngine(profile, VIEWPORT)
  const hand = new SimHand({ pose: 'palm', span: spanForDistance(3) })
  let now = 0

  /** One real frame. Clicks and scroll are one-frame events, so tests that
   *  count them must step rather than sample the last frame of a burst. */
  const step = (pose?: SimPose): ReturnType<AirEngine['update']> => {
    if (pose) hand.pose = pose
    now += 16
    return engine.update(hand.landmarks(), now)
  }

  const drive = (ms: number, pose?: SimPose): ReturnType<AirEngine['update']> => {
    let state = step(pose)
    for (let elapsed = 16; elapsed < ms; elapsed += 16) state = step(pose)
    return state
  }

  return { engine, hand, drive, step, now: () => now }
}

function armed(profile = DEFAULT_PROFILE) {
  const r = rig(profile)
  r.drive(900, 'palm')
  return r
}

describe('pose classification', () => {
  it('recognises each pose near and far', () => {
    for (const feet of [3, 9]) {
      expect(poseAt('point', feet)).toBe('point')
      expect(poseAt('palm', feet)).toBe('palm')
      expect(poseAt('fist', feet)).toBe('fist')
      expect(poseAt('pinch', feet)).toBe('pinch')
      expect(poseAt('two', feet)).toBe('two')
    }
  })

  it('never reads a pinch as an open palm', () => {
    // The "heart" collision: if these overlapped, a click could arm the tracker.
    expect(poseAt('pinch')).toBe('pinch')
  })

  it('survives a rotated hand', () => {
    for (const angle of [-0.5, 0, 0.5]) {
      const hand = new SimHand({ pose: 'point', angle, span: spanForDistance(9) }).landmarks()
      expect(classifyPose(hand, DEFAULT_PROFILE.pinchRatio)).toBe('point')
    }
  })
})

describe('distance handling', () => {
  it('reports 1x at the calibration distance and grows with distance', () => {
    const near = handScale(new SimHand({ span: 0.075 }).landmarks())
    expect(distanceRatio(near, 0.075)).toBeCloseTo(1, 3)
    const far = handScale(new SimHand({ span: 0.025 }).landmarks())
    expect(distanceRatio(far, 0.075)).toBeCloseTo(3, 2)
  })

  it('makes the cursor bigger when farther away', () => {
    const near = cursorRadiusPx(18, 1, 2.4)
    const far = cursorRadiusPx(18, 3, 2.4)
    expect(far).toBeGreaterThan(near * 2)
    expect(cursorRadiusPx(18, 40, 2.4)).toBeCloseTo(43.2, 1)
    expect(cursorRadiusPx(18, 0.3, 2.4)).toBeGreaterThanOrEqual(15)
  })

  it('maps the calibrated box to the whole viewport', () => {
    const bounds = { minX: 0.3, maxX: 0.7, minY: 0.2, maxY: 0.8 }
    expect(mapToScreen({ x: 0.3, y: 0.2 }, bounds, VIEWPORT).x).toBe(0)
    expect(mapToScreen({ x: 0.7, y: 0.8 }, bounds, VIEWPORT).x).toBe(VIEWPORT.width)
    const middle = mapToScreen({ x: 0.5, y: 0.5 }, bounds, VIEWPORT)
    expect(middle.x).toBeCloseTo(VIEWPORT.width / 2, 0)
    expect(middle.y).toBeCloseTo(VIEWPORT.height / 2, 0)
  })
})

describe('calibration', () => {
  it('trims a tracking glitch out of the reach box', () => {
    const points = []
    for (let i = 0; i < 100; i += 1) {
      points.push({ x: 0.3 + (i % 10) * 0.04, y: 0.3 + (i % 7) * 0.05 })
    }
    points.push({ x: 0.01, y: 0.99 })
    const bounds = boundsFromSamples(points)
    expect(bounds.minX).toBeGreaterThanOrEqual(0.25)
    expect(bounds.maxY).toBeLessThanOrEqual(0.75)
  })

  it('guesses a pinch threshold between pinched and open gaps', () => {
    const threshold = pinchThresholdFromSamples(
      [0.08, 0.12, 0.16, 0.2],
      [0.95, 1.1, 1.3, 1.5],
    )
    expect(threshold).toBeGreaterThan(0.2)
    expect(threshold).toBeLessThan(0.95)
  })

  it('derives smoothing from measured jitter', () => {
    const steady = buildProfile({
      bounds: DEFAULT_PROFILE.bounds,
      referenceSpan: 0.075,
      jitterRmsPx: 0.5,
    })
    const shaky = buildProfile({
      bounds: DEFAULT_PROFILE.bounds,
      referenceSpan: 0.075,
      jitterRmsPx: 8,
    })
    expect(shaky.smoothing.minCutoff).toBeLessThan(steady.smoothing.minCutoff)
    expect(shaky.smoothing.deadzonePx).toBeGreaterThan(steady.smoothing.deadzonePx)
    expect(shaky.jitter.score).toBeLessThan(steady.jitter.score)
  })

  it('repairs a corrupt stored profile instead of trusting it', () => {
    const bad = normalizeProfile({
      bounds: { minX: 5, maxX: 9, minY: -3, maxY: 9 },
      cursor: { basePx: 900 },
      click: { mode: 'nonsense', dwellSeconds: 90 },
      smoothing: { minCutoff: 0 },
    })
    expect(bad.bounds.minX).toBeLessThan(bad.bounds.maxX)
    expect(bad.cursor.basePx).toBeLessThanOrEqual(44)
    expect(bad.click.mode).toBe('dwell')
    expect(bad.click.dwellSeconds).toBeLessThanOrEqual(3)
    expect(bad.smoothing.minCutoff).toBeGreaterThanOrEqual(0.35)
  })
})

describe('jitter meter', () => {
  it('scores a still signal high and a shaking one low', () => {
    const still = new JitterMeter()
    for (let i = 0; i < 60; i += 1) still.push({ x: 400, y: 300 })
    expect(still.score).toBe(100)

    const shaking = new JitterMeter()
    let seed = 3
    const random = () => {
      seed = (seed * 16807) % 2147483647
      return seed / 2147483647
    }
    for (let i = 0; i < 60; i += 1) {
      shaking.push({ x: 400 + (random() - 0.5) * 18, y: 300 + (random() - 0.5) * 18 })
    }
    expect(shaking.score).toBeLessThan(70)
    expect(shaking.rms).toBeGreaterThan(1)
  })

  it('tunes smoother settings for shakier hands', () => {
    const calm = tuneFromJitter(0.5)
    const shaky = tuneFromJitter(9)
    expect(shaky.minCutoff).toBeLessThan(calm.minCutoff)
    expect(shaky.minSpeedPxPerSec).toBeGreaterThan(calm.minSpeedPxPerSec)
    expect(shaky.deadzonePx).toBeGreaterThan(calm.deadzonePx)
  })
})

describe('engine state machine', () => {
  it('starts armed and does not move on a pointing hand', () => {
    const r = rig()
    const state = r.drive(400, 'point')
    expect(state.state).toBe('armed')
    expect(state.cursor).toBeNull()
  })

  it('arms after the palm hold, then moves the cursor', () => {
    const r = armed()
    expect(r.engine.state).toBe('active')

    // The preview is mirrored: a hand on the camera's left is the user's right,
    // so raw x = 0.25 must land on the right-hand side of the screen.
    r.hand.x = 0.25
    const state = r.drive(1200, 'point')
    expect(state.cursor).not.toBeNull()
    expect(state.cursor!.x).toBeGreaterThan(1000)
  })

  it('releases on a held fist', () => {
    const r = armed()
    r.drive(700, 'fist')
    expect(r.engine.state).toBe('armed')
  })

  it('enlarges the cursor when the hand is farther away', () => {
    const near = armed()
    const nearRadius = near.drive(200, 'point').cursor!.radius

    const farProfile = { ...DEFAULT_PROFILE, referenceSpan: 0.075 }
    const far = armed(farProfile)
    far.hand.span = spanForDistance(10)
    const farRadius = far.drive(200, 'point').cursor!.radius

    expect(farRadius).toBeGreaterThan(nearRadius * 1.5)
  })

  it('does not drift on a still hand with detector noise', () => {
    const r = armed()
    r.drive(300, 'point')
    const before = { ...r.engine.update(r.hand.landmarks(), r.now()).cursor! }
    r.hand.jitter = 1.5 / 1280
    const state = r.drive(3000, 'point')
    expect(Math.abs(state.cursor!.x - before.x)).toBeLessThan(25)
    expect(Math.abs(state.cursor!.y - before.y)).toBeLessThan(25)
  })
})

describe('clicking', () => {
  it('clicks once when holding still (dwell)', () => {
    const profile = {
      ...DEFAULT_PROFILE,
      click: { ...DEFAULT_PROFILE.click, mode: 'dwell' as const, dwellSeconds: 0.8 },
    }
    const r = armed(profile)
    let clicks = 0
    let kind: string | undefined
    r.drive(200, 'point')
    for (let i = 0; i < 90; i += 1) {
      const state = r.step('point')
      if (state.click) {
        clicks += 1
        kind = state.click.kind
      }
    }
    expect(clicks).toBe(1)
    expect(kind).toBe('dwell')
  })

  it('clicks once per pinch, and only after a pointing frame', () => {
    const profile = {
      ...DEFAULT_PROFILE,
      click: { ...DEFAULT_PROFILE.click, mode: 'pinch' as const },
    }
    const r = armed(profile)
    let clicks = 0

    // Already pinched, never pointed: must not click.
    for (let i = 0; i < 60; i += 1) {
      const state = r.step('pinch')
      if (state.click) clicks += 1
    }
    expect(clicks).toBe(0)

    r.drive(500, 'point')
    for (let i = 0; i < 30; i += 1) {
      const state = r.step('pinch')
      if (state.click) clicks += 1
    }
    expect(clicks).toBe(1)
  })

  it('reports scroll pixels for the two-finger pose', () => {
    const r = armed()
    r.drive(200, 'two')
    let scroll = 0
    for (let i = 0; i < 10; i += 1) {
      r.hand.y -= 0.006
      scroll += r.step('two').scroll
    }
    expect(scroll).toBeGreaterThan(0)
  })
})
