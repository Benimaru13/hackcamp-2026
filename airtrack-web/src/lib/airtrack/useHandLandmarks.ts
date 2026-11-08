/**
 * Camera + MediaPipe HandLandmarker loop.
 *
 * Uses the browser's own camera and the Tasks Web SDK, so nothing but the
 * landmarks ever leaves the page and no Python/OpenCV install is needed. The
 * synthetic-hand mode runs the identical loop without a camera, which is what
 * makes the demo work on a machine with a broken webcam.
 */

import { useEffect, useRef, useState, type RefObject } from 'react'
import { FilesetResolver, HandLandmarker } from '@mediapipe/tasks-vision'
import { drawOverlay } from './overlay'
import { SimHand } from './simulate'
import type { Landmark } from './types'

/** Served from public/ so the demo does not depend on a CDN at the venue. */
export const WASM_PATH = '/mediapipe/wasm'
export const MODEL_PATH = '/models/hand_landmarker.task'

export type TrackingStatus = 'idle' | 'loading' | 'ready' | 'error'

export interface UseHandLandmarksOptions {
  enabled: boolean
  simulate: boolean
  videoRef: RefObject<HTMLVideoElement | null>
  canvasRef: RefObject<HTMLCanvasElement | null>
  onFrame?: (landmarks: Landmark[] | null, nowMs: number) => void
  onFps?: (fps: number) => void
  showSkeleton?: boolean
}

export function useHandLandmarks({
  enabled,
  simulate,
  videoRef,
  canvasRef,
  onFrame,
  onFps,
  showSkeleton = true,
}: UseHandLandmarksOptions): { status: TrackingStatus; error: string | null } {
  const [status, setStatus] = useState<TrackingStatus>('idle')
  const [error, setError] = useState<string | null>(null)

  const landmarkerRef = useRef<HandLandmarker | null>(null)
  const simRef = useRef<SimHand | null>(null)
  const onFrameRef = useRef(onFrame)
  const onFpsRef = useRef(onFps)
  const showSkeletonRef = useRef(showSkeleton)

  onFrameRef.current = onFrame
  onFpsRef.current = onFps
  showSkeletonRef.current = showSkeleton

  // Camera + model lifecycle.
  useEffect(() => {
    if (!enabled) {
      setStatus('idle')
      return
    }
    let cancelled = false
    let stream: MediaStream | null = null

    async function setup() {
      setError(null)
      setStatus('loading')
      simRef.current = simulate
        ? new SimHand({ x: 0.5, y: 0.55, span: 0.075, pose: 'point', seed: 7 })
        : null

      if (simulate) {
        if (!cancelled) setStatus('ready')
        return
      }

      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          throw new Error('This browser cannot open a camera (no getUserMedia).')
        }
        stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' },
          audio: false,
        })
        if (cancelled) return
        const video = videoRef.current
        if (!video) throw new Error('Camera preview element is missing.')
        video.srcObject = stream
        video.muted = true
        await video.play().catch(() => undefined)

        const fileset = await FilesetResolver.forVisionTasks(WASM_PATH)
        const create = (delegate: 'GPU' | 'CPU') =>
          HandLandmarker.createFromOptions(fileset, {
            baseOptions: { modelAssetPath: MODEL_PATH, delegate },
            runningMode: 'VIDEO',
            numHands: 1,
            // Low on purpose: the hand is small at 3 m, and a missed frame is
            // cheaper than a false one (the gate rejects the latter).
            minHandDetectionConfidence: 0.3,
            minHandPresenceConfidence: 0.3,
            minTrackingConfidence: 0.3,
          })

        let landmarker: HandLandmarker
        try {
          landmarker = await create('GPU')
        } catch {
          landmarker = await create('CPU')
        }
        if (cancelled) {
          landmarker.close()
          return
        }
        landmarkerRef.current = landmarker
        setStatus('ready')
      } catch (err) {
        if (cancelled) return
        const message =
          err instanceof Error ? err.message : 'Camera or hand model could not start.'
        setError(
          /permission|denied|NotAllowed/i.test(message)
            ? 'Camera permission was denied. Allow it in the browser, or use simulate mode.'
            : message,
        )
        setStatus('error')
      }
    }

    void setup()

    return () => {
      cancelled = true
      landmarkerRef.current?.close()
      landmarkerRef.current = null
      simRef.current = null
      stream?.getTracks().forEach((track) => track.stop())
      const video = videoRef.current
      if (video) video.srcObject = null
    }
  }, [enabled, simulate, videoRef])

  // Frame loop. Restarts only when the source changes; the latest onFrame is
  // read through a ref so a re-render never drops a frame.
  useEffect(() => {
    if (!enabled || status !== 'ready') return
    let raf = 0
    let lastFpsAt = 0
    let frames = 0

    const loop = (nowMs: number) => {
      raf = requestAnimationFrame(loop)
      const video = videoRef.current
      const canvas = canvasRef.current
      let landmarks: Landmark[] | null = null

      if (simRef.current) {
        const sim = simRef.current
        // Wander slowly around the frame so the cursor visibly tracks the hand.
        const t = nowMs / 1000
        sim.x = 0.5 + Math.sin(t * 0.45) * 0.16
        sim.y = 0.55 + Math.cos(t * 0.33) * 0.12
        landmarks = sim.landmarks()
      } else if (landmarkerRef.current && video && video.readyState >= 2) {
        const result = landmarkerRef.current.detectForVideo(video, nowMs)
        const hand = result.landmarks?.[0]
        if (hand) landmarks = hand.map((p) => ({ x: p.x, y: p.y, z: p.z }))
      }

      if (canvas && showSkeletonRef.current) {
        drawOverlay(canvas, landmarks, { mirror: true })
      }

      onFrameRef.current?.(landmarks, nowMs)

      frames += 1
      if (lastFpsAt === 0) lastFpsAt = nowMs
      const windowMs = nowMs - lastFpsAt
      if (windowMs >= 500) {
        onFpsRef.current?.(Math.round((frames * 1000) / windowMs))
        frames = 0
        lastFpsAt = nowMs
      }
    }

    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [enabled, simulate, status, videoRef, canvasRef])

  return { status, error }
}

/** Air clicks become real DOM clicks on the nearest `[data-air-target]`. */
export function dispatchAirClick(x: number, y: number): HTMLElement | null {
  const hit = document.elementFromPoint(x, y)
  const target = hit?.closest('[data-air-target]')
  if (target instanceof HTMLElement) {
    target.click()
    return target
  }
  return null
}
