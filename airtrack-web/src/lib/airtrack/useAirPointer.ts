/**
 * One hook that turns landmarks into a real air pointer: cursor element,
 * dwell/pinch clicks on `[data-air-target]`, two-finger scrolling, and a HUD
 * snapshot at ~8 Hz (frame-rate React updates would make the page janky).
 *
 * Both the tracker and the calibration wizard use it, so the interaction you
 * calibrate with is the interaction you get.
 */

import { useCallback, useEffect, useRef, type RefObject } from 'react'
import type { CalibrationProfile } from './calibration'
import { AirEngine, type AirState } from './engine'
import type { Landmark } from './types'
import {
  dispatchAirClick,
  useHandLandmarks,
  type TrackingStatus,
} from './useHandLandmarks'

export interface AirPointerOptions {
  enabled?: boolean
  simulate: boolean
  profile: CalibrationProfile
  /** Start controlling immediately (calibration) instead of waiting for a palm. */
  autoArm?: boolean
  videoRef: RefObject<HTMLVideoElement | null>
  canvasRef: RefObject<HTMLCanvasElement | null>
  cursorRef: RefObject<HTMLDivElement | null>
  onHud?: (state: AirState, fps: number) => void
  onScroll?: (deltaPx: number) => void
  onLandmarks?: (landmarks: Landmark[] | null, nowMs: number) => void
  showSkeleton?: boolean
}

export interface AirPointer {
  status: TrackingStatus
  error: string | null
  engineRef: RefObject<AirEngine | null>
}

export function useAirPointer({
  enabled = true,
  simulate,
  profile,
  autoArm = false,
  videoRef,
  canvasRef,
  cursorRef,
  onHud,
  onScroll,
  onLandmarks,
  showSkeleton = true,
}: AirPointerOptions): AirPointer {
  const engineRef = useRef<AirEngine | null>(null)
  const onHudRef = useRef(onHud)
  const onScrollRef = useRef(onScroll)
  const onLandmarksRef = useRef(onLandmarks)
  const fpsRef = useRef(0)
  const lastHudAt = useRef(0)

  onHudRef.current = onHud
  onScrollRef.current = onScroll
  onLandmarksRef.current = onLandmarks

  if (!engineRef.current && typeof window !== 'undefined') {
    engineRef.current = new AirEngine(profile, {
      width: window.innerWidth,
      height: window.innerHeight,
    })
  }

  useEffect(() => {
    engineRef.current?.setProfile(profile)
  }, [profile])

  useEffect(() => {
    const onResize = () => {
      engineRef.current?.setViewport({
        width: window.innerWidth,
        height: window.innerHeight,
      })
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const clearCursor = useCallback(() => {
    const el = cursorRef.current
    if (!el) return
    el.style.display = 'none'
    el.style.setProperty('--dwell', '0')
  }, [cursorRef])

  const handleFrame = useCallback(
    (landmarks: Landmark[] | null, nowMs: number) => {
      const engine = engineRef.current
      if (!engine) return
      const state = engine.update(landmarks, nowMs)
      const el = cursorRef.current

      if (el) {
        const { cursor } = state
        if (cursor) {
          const size = Math.max(cursor.radius * 2, 16)
          el.style.display = 'block'
          el.style.width = `${size}px`
          el.style.height = `${size}px`
          el.style.left = `${cursor.x - size / 2}px`
          el.style.top = `${cursor.y - size / 2}px`
          el.style.setProperty('--dwell', String(state.dwell?.progress ?? 0))
          el.dataset.state = state.state
        } else {
          clearCursor()
        }
      }

      if (state.click) dispatchAirClick(state.click.x, state.click.y)
      if (state.scroll && onScrollRef.current) onScrollRef.current(state.scroll)
      onLandmarksRef.current?.(landmarks, nowMs)

      if (nowMs - lastHudAt.current > 120) {
        lastHudAt.current = nowMs
        onHudRef.current?.(state, fpsRef.current)
      }
    },
    [clearCursor, cursorRef],
  )

  const tracking = useHandLandmarks({
    enabled,
    simulate,
    videoRef,
    canvasRef,
    onFrame: handleFrame,
    onFps: (fps) => {
      fpsRef.current = fps
    },
    showSkeleton,
  })

  useEffect(() => {
    if (tracking.status !== 'ready' || !autoArm) return
    engineRef.current?.arm(performance.now())
  }, [tracking.status, autoArm])

  useEffect(() => {
    if (tracking.status !== 'ready') clearCursor()
  }, [tracking.status, clearCursor])

  return { status: tracking.status, error: tracking.error, engineRef }
}
