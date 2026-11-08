/**
 * Synthetic hands — the same shapes the Python prototype used, so the whole
 * pipeline can be exercised without a camera: unit tests, the calibrator's
 * dry run, and the "simulate" toggle used when a venue webcam misbehaves.
 *
 * Geometry is authored in palm-length units with the wrist at the origin and
 * the fingers pointing up (-y). `handScale` (wrist → middle knuckle) is 1.0 by
 * construction, so multiplying by a span gives the normalized frame position.
 */

import type { Landmark, Pose } from './types'

type PalmPose = Exclude<Pose, 'none' | 'hand'>

const FINGER_GEOMETRY: Record<string, { mcp: [number, number]; dir: [number, number] }> = {
  index: { mcp: [-0.36, -0.95], dir: [-0.1, -1.0] },
  middle: { mcp: [0.0, -1.0], dir: [0.0, -1.0] },
  ring: { mcp: [0.3, -0.92], dir: [0.09, -1.0] },
  pinky: { mcp: [0.56, -0.8], dir: [0.2, -1.0] },
}

const EXTENDED: Record<PalmPose, string[]> = {
  point: ['index'],
  palm: ['index', 'middle', 'ring', 'pinky'],
  pinch: ['index'],
  fist: [],
  two: ['index', 'middle'],
}

const THUMB_OPEN: Array<[number, number]> = [
  [0.3, 0.02],
  [0.62, -0.22],
  [0.86, -0.46],
  [1.06, -0.68],
]

const THUMB_TUCK: Array<[number, number]> = [
  [0.3, 0.02],
  [0.55, -0.24],
  [0.55, -0.55],
  [0.3, -0.7],
]

function fingerTip(name: string): [number, number] {
  const { mcp, dir } = FINGER_GEOMETRY[name]
  const n = Math.hypot(dir[0], dir[1])
  return [mcp[0] + (dir[0] / n) * 1.02, mcp[1] + (dir[1] / n) * 1.02]
}

/** 21 points (x, y) in palm-length units, wrist first. */
export function handTemplate(pose: PalmPose = 'point'): Array<[number, number]> {
  const extended = new Set(EXTENDED[pose])
  const points: Array<[number, number]> = [[0, 0]]

  let thumb = pose === 'fist' ? THUMB_TUCK : THUMB_OPEN
  if (pose === 'pinch') {
    const tip = fingerTip('index')
    thumb = [
      [0.3, 0.02],
      [0.2, -0.6],
      [-0.1, -1.35],
      [tip[0] + 0.01, tip[1] + 0.01],
    ]
  }
  points.push(...thumb)

  for (const name of ['index', 'middle', 'ring', 'pinky']) {
    const { mcp, dir } = FINGER_GEOMETRY[name]
    const n = Math.hypot(dir[0], dir[1])
    const ux = dir[0] / n
    const uy = dir[1] / n
    const reach = (k: number): [number, number] => [mcp[0] + ux * k, mcp[1] + uy * k]
    const [pip, dip, tip] = extended.has(name)
      ? [reach(0.5), reach(0.78), reach(1.02)]
      : [reach(0.42), reach(0.28), reach(0.1)]
    points.push(mcp, pip, dip, tip)
  }

  return points.slice(0, 21)
}

/** Deterministic RNG so simulated jitter is reproducible in tests. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function gaussian(random: () => number): number {
  const u = Math.max(random(), 1e-9)
  const v = random()
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v)
}

export interface SimHandOptions {
  x?: number
  y?: number
  span?: number
  pose?: PalmPose
  angle?: number
  /** Per-axis gaussian sigma in normalized frame units. */
  jitter?: number
  seed?: number
}

export class SimHand {
  x: number
  y: number
  span: number
  pose: PalmPose
  angle: number
  jitter: number
  private random: () => number

  constructor(options: SimHandOptions = {}) {
    this.x = options.x ?? 0.5
    this.y = options.y ?? 0.55
    this.span = options.span ?? 0.075
    this.pose = options.pose ?? 'point'
    this.angle = options.angle ?? 0
    this.jitter = options.jitter ?? 0
    this.random = mulberry32(options.seed ?? 1)
  }

  landmarks(pose?: PalmPose): Landmark[] {
    if (pose) this.pose = pose
    const cos = Math.cos(this.angle)
    const sin = Math.sin(this.angle)
    return handTemplate(this.pose).map(([lx, ly]) => {
      const rx = lx * cos - ly * sin
      const ry = lx * sin + ly * cos
      return {
        x: this.x + rx * this.span + (this.jitter ? gaussian(this.random) * this.jitter : 0),
        y: this.y + ry * this.span + (this.jitter ? gaussian(this.random) * this.jitter : 0),
      }
    })
  }

  move(dx = 0, dy = 0): this {
    this.x += dx
    this.y += dy
    return this
  }
}

/** Hand span (fraction of frame width) for a hand `feet` from a 60° webcam. */
export function spanForDistance(feet: number, referenceFeet = 3, referenceSpan = 0.075): number {
  const safeFeet = Math.max(feet, 0.5)
  return referenceSpan * (referenceFeet / safeFeet)
}
