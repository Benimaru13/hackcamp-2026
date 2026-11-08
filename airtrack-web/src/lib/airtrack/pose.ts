/**
 * Pose classification.
 *
 * All tests use distances measured from the wrist and divided by the hand's own
 * size, so they survive rotation and camera distance. Finger extension compares
 * the fingertip to the middle joint measured from the wrist — never the raw y
 * coordinate, which breaks when the camera looks down at you.
 */

import { dist, handScale, pinchGap } from './geometry'
import type { Landmark, Pose } from './types'
import { LM } from './types'

const FINGERS: ReadonlyArray<readonly [number, number]> = [
  [LM.INDEX_TIP, LM.INDEX_PIP],
  [LM.MIDDLE_TIP, LM.MIDDLE_PIP],
  [LM.RING_TIP, LM.RING_PIP],
  [LM.PINKY_TIP, LM.PINKY_PIP],
]

function extended(lm: Landmark[], tip: number, pip: number, k = 1.12): boolean {
  const wrist = lm[LM.WRIST]
  return dist(lm[tip], wrist) > dist(lm[pip], wrist) * k
}

function curled(lm: Landmark[], tip: number, pip: number, k = 1.02): boolean {
  const wrist = lm[LM.WRIST]
  return dist(lm[tip], wrist) < dist(lm[pip], wrist) * k
}

/** [index, middle, ring, pinky] — the four fingers that carry the pose. */
export function fingersUp(lm: Landmark[]): boolean[] {
  return FINGERS.map(([tip, pip]) => extended(lm, tip, pip))
}

export function isPointing(lm: Landmark[]): boolean {
  const [index, middle, ring, pinky] = fingersUp(lm)
  return index && !middle && !ring && !pinky
}

export function isPinching(lm: Landmark[], pinchRatio: number): boolean {
  return pinchGap(lm) < pinchRatio
}

/**
 * Open palm = all four fingers up AND the thumb clearly away from the index
 * tip. The second half is what stops the click pinch from arming the tracker —
 * the "heart" gesture collision the team hit.
 */
export function isOpenPalm(lm: Landmark[], pinchRatio: number): boolean {
  if (!fingersUp(lm).every(Boolean)) return false
  return pinchGap(lm) > Math.max(0.55, pinchRatio * 1.7)
}

export function isFist(lm: Landmark[]): boolean {
  if (fingersUp(lm).some(Boolean)) return false
  if (!FINGERS.every(([tip, pip]) => curled(lm, tip, pip))) return false
  const scale = handScale(lm)
  return FINGERS.every(([tip]) => dist(lm[tip], lm[LM.WRIST]) < 1.45 * scale)
}

/** Index + middle up, ring + pinky down: the two-finger scroll pose. */
export function isTwoFinger(lm: Landmark[]): boolean {
  const [index, middle, ring, pinky] = fingersUp(lm)
  return index && middle && !ring && !pinky
}

/**
 * One label, ordered so a deliberate stop beats a click, and a click beats
 * arming or moving. Mirrors the priority used by the state machine.
 */
export function classifyPose(lm: Landmark[] | null, pinchRatio: number): Pose {
  if (!lm || lm.length < 21) return 'none'
  if (isFist(lm)) return 'fist'
  if (isPinching(lm, pinchRatio)) return 'pinch'
  if (isOpenPalm(lm, pinchRatio)) return 'palm'
  if (isTwoFinger(lm)) return 'two'
  if (isPointing(lm)) return 'point'
  return 'hand'
}
