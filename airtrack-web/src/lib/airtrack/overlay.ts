/**
 * Canvas overlay for the camera preview: hand skeleton + reach box.
 * Kept out of React on purpose — this redraws at camera frame rate, and a
 * state update per frame would re-render the whole page 30 times a second.
 */

import type { Bounds, Landmark } from './types'

const CONNECTIONS: ReadonlyArray<readonly [number, number]> = [
  // palm
  [0, 5],
  [5, 9],
  [9, 13],
  [13, 17],
  [17, 0],
  // thumb
  [1, 2],
  [2, 3],
  [3, 4],
  // index
  [5, 6],
  [6, 7],
  [7, 8],
  // middle
  [9, 10],
  [10, 11],
  [11, 12],
  // ring
  [13, 14],
  [14, 15],
  [15, 16],
  // pinky
  [17, 18],
  [18, 19],
  [19, 20],
]

export function resizeCanvas(canvas: HTMLCanvasElement): CanvasRenderingContext2D | null {
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  const rect = canvas.getBoundingClientRect()
  const width = Math.max(Math.round(rect.width * dpr), 1)
  const height = Math.max(Math.round(rect.height * dpr), 1)
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width
    canvas.height = height
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  return ctx
}

export interface OverlayOptions {
  mirror: boolean
  /** Calibrated reach box, drawn as a soft guide. */
  bounds?: Bounds
  accent?: string
}

export function drawOverlay(
  canvas: HTMLCanvasElement,
  landmarks: Landmark[] | null,
  options: OverlayOptions,
): void {
  const ctx = resizeCanvas(canvas)
  if (!ctx) return
  const rect = canvas.getBoundingClientRect()
  if (rect.width < 2 || rect.height < 2) return
  const accent = options.accent ?? '#818cf8'

  ctx.clearRect(0, 0, rect.width, rect.height)

  if (options.bounds) {
    const b = options.bounds
    const x0 = (options.mirror ? 1 - b.maxX : b.minX) * rect.width
    const x1 = (options.mirror ? 1 - b.minX : b.maxX) * rect.width
    ctx.strokeStyle = 'rgba(129, 140, 248, 0.28)'
    ctx.setLineDash([6, 6])
    ctx.lineWidth = 1
    ctx.strokeRect(
      Math.min(x0, x1),
      b.minY * rect.height,
      Math.abs(x1 - x0),
      (b.maxY - b.minY) * rect.height,
    )
    ctx.setLineDash([])
  }

  if (!landmarks || landmarks.length < 21) return

  const at = (index: number): [number, number] => {
    const p = landmarks[index]
    const x = options.mirror ? 1 - p.x : p.x
    return [x * rect.width, p.y * rect.height]
  }

  ctx.strokeStyle = 'rgba(232, 234, 237, 0.55)'
  ctx.lineWidth = 2
  ctx.lineCap = 'round'
  for (const [a, b] of CONNECTIONS) {
    const [ax, ay] = at(a)
    const [bx, by] = at(b)
    ctx.beginPath()
    ctx.moveTo(ax, ay)
    ctx.lineTo(bx, by)
    ctx.stroke()
  }

  cfgPoints(ctx, rect, landmarks, accent)
  const [tipX, tipY] = at(8)
  ctx.beginPath()
  ctx.arc(tipX, tipY, 5, 0, Math.PI * 2)
  ctx.fillStyle = accent
  ctx.fill()
}

function cfgPoints(
  ctx: CanvasRenderingContext2D,
  rect: { width: number; height: number },
  landmarks: Landmark[],
  accent: string,
): void {
  for (let i = 0; i < landmarks.length; i += 1) {
    const p = landmarks[i]
    ctx.beginPath()
    ctx.arc(p.x * rect.width, p.y * rect.height, i % 4 === 0 ? 2.5 : 1.8, 0, Math.PI * 2)
    ctx.fillStyle = i === 8 ? accent : 'rgba(232, 234, 237, 0.85)'
    ctx.fill()
  }
}
