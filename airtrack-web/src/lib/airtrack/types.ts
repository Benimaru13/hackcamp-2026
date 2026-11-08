/**
 * Shared types for the AirTrack pipeline.
 *
 * A landmark is any object with normalized frame coordinates (0..1, y grows
 * downward) — the same shape MediaPipe's HandLandmarker returns, so the pure
 * logic here is testable with synthetic hands and never needs a camera.
 */

export interface Landmark {
  x: number
  y: number
  z?: number
}

export interface Vec2 {
  x: number
  y: number
}

export interface Bounds {
  minX: number
  maxX: number
  minY: number
  maxY: number
}

/** Pose labels used in the HUD and the state machine. */
export type Pose = 'none' | 'point' | 'pinch' | 'palm' | 'fist' | 'two' | 'hand'

export type ControlState = 'armed' | 'active'

export type JitterLevel = 'smooth' | 'steady' | 'shaky' | 'very shaky'

/** MediaPipe hand landmark indices, named so the logic reads like prose. */
export const LM = {
  WRIST: 0,
  THUMB_TIP: 4,
  INDEX_MCP: 5,
  INDEX_PIP: 6,
  INDEX_TIP: 8,
  MIDDLE_MCP: 9,
  MIDDLE_PIP: 10,
  MIDDLE_TIP: 12,
  RING_MCP: 13,
  RING_PIP: 14,
  RING_TIP: 16,
  PINKY_MCP: 17,
  PINKY_PIP: 18,
  PINKY_TIP: 20,
} as const
