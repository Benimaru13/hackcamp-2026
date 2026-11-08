/**
 * The calibrator.
 *
 * Four measured steps, one saved profile:
 *   1. camera check         — is a hand visible at all?
 *   2. reach box (8 s)      — the box you can comfortably point at
 *   3. pinch test (6 s)     — your own pinch distance, not a guessed constant
 *   4. stillness (4 s)      — your jitter, which sets smoothing and deadzone
 *
 * Every button is a `[data-air-target]`, and the pointer is armed automatically
 * here, so the wizard itself can be driven by the same air gestures it is
 * calibrating.
 */

import { useCallback, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutations } from 'deepspace'
import { AirCursor } from '@/components/airtrack/AirCursor'
import {
  DEFAULT_PROFILE,
  averageHandScale,
  boundsFromSamples,
  buildProfile,
  pinchThresholdFromSamples,
  type ClickMode,
} from '@/lib/airtrack/calibration'
import type { Bounds } from '@/lib/airtrack/types'
import type { AirState } from '@/lib/airtrack/engine'
import { JitterMeter } from '@/lib/airtrack/filter'
import { mapToScreen, mirrorPoint, pinchGap } from '@/lib/airtrack/geometry'
import { saveActiveProfile } from '@/lib/airtrack/store'
import type { Landmark } from '@/lib/airtrack/types'
import { useAirPointer } from '@/lib/airtrack/useAirPointer'
import { cn } from '@/lib/utils'
import type { CalibrationProfileRecord } from '@/schemas/profiles-schema'

const DURATIONS = [0, 8000, 6000, 4000, 0]
const STEP_TITLES = ['Camera', 'Reach box', 'Pinch', 'Stillness', 'Save']

interface Measured {
  bounds?: Bounds
  span?: number
  pinchRatio?: number
  jitterRmsPx?: number
}

export default function CalibratePage() {
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [measured, setMeasured] = useState<Measured>({})
  const [collecting, setCollecting] = useState(false)
  const [progress, setProgress] = useState(0)
  const [handSeen, setHandSeen] = useState(false)
  const [simulate, setSimulate] = useState(false)
  const [name, setName] = useState('My profile')
  const [distanceFt, setDistanceFt] = useState(DEFAULT_PROFILE.referenceDistanceFt)
  const [clickMode, setClickMode] = useState<ClickMode>('dwell')
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'error'>('idle')

  const videoRef = useRef<HTMLVideoElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const cursorRef = useRef<HTMLDivElement | null>(null)

  const samplesRef = useRef<{ x: number; y: number }[]>([])
  const handsRef = useRef<Landmark[][]>([])
  const tightRef = useRef<number[]>([])
  const openRef = useRef<number[]>([])
  const jitterRef = useRef(new JitterMeter())
  const stepRef = useRef(0)
  const collectingRef = useRef(false)
  const startRef = useRef(0)
  const durationRef = useRef(0)
  const progressRef = useRef(0)
  const measuredRef = useRef<Measured>(measured)
  const handSeenRef = useRef(false)

  measuredRef.current = measured

  const { createConfirmed } = useMutations<CalibrationProfileRecord>('calibration_profiles')

  const finishStep = useCallback((index: number) => {
    if (!collectingRef.current) return
    collectingRef.current = false
    setCollecting(false)
    progressRef.current = 1
    setProgress(1)

    if (index === 1) {
      setMeasured((prev) => ({
        ...prev,
        bounds: boundsFromSamples(samplesRef.current),
        span: averageHandScale(handsRef.current),
      }))
    } else if (index === 2) {
      setMeasured((prev) => ({
        ...prev,
        pinchRatio: pinchThresholdFromSamples(tightRef.current, openRef.current),
      }))
    } else if (index === 3) {
      setMeasured((prev) => ({
        ...prev,
        jitterRmsPx: Math.round(jitterRef.current.rms * 100) / 100,
      }))
    }
  }, [])

  const onLandmarks = useCallback(
    (landmarks: Landmark[] | null, nowMs: number) => {
      const seen = !!landmarks && landmarks.length >= 21
      if (seen !== handSeenRef.current) {
        handSeenRef.current = seen
        setHandSeen(seen)
      }
      if (!landmarks || landmarks.length < 21 || !collectingRef.current) return

      const index = stepRef.current
      const tip = mirrorPoint(
        { x: landmarks[8].x, y: landmarks[8].y },
        true,
      )

      if (index === 1) {
        samplesRef.current.push(tip)
        if (handsRef.current.length < 240) handsRef.current.push(landmarks)
      } else if (index === 2) {
        const gap = pinchGap(landmarks)
        if (gap < 0.5) tightRef.current.push(gap)
        else if (gap > 0.85) openRef.current.push(gap)
      } else if (index === 3) {
        const bounds = measuredRef.current.bounds ?? DEFAULT_PROFILE.bounds
        jitterRef.current.push(
          mapToScreen(tip, bounds, {
            width: window.innerWidth,
            height: window.innerHeight,
          }),
        )
      }

      const elapsed = nowMs - startRef.current
      const next = Math.min(1, elapsed / Math.max(durationRef.current, 1))
      if (next - progressRef.current > 0.02) {
        progressRef.current = next
        setProgress(next)
      }
      if (elapsed >= durationRef.current) finishStep(index)
    },
    [finishStep],
  )

  const pointer = useAirPointer({
    simulate,
    profile: DEFAULT_PROFILE,
    autoArm: true,
    videoRef,
    canvasRef,
    cursorRef,
    onLandmarks,
    onHud: (state: AirState) => {
      if (state.handDetected !== handSeenRef.current) {
        handSeenRef.current = state.handDetected
        setHandSeen(state.handDetected)
      }
    },
  })

  const startStep = (index: number) => {
    samplesRef.current = []
    handsRef.current = []
    tightRef.current = []
    openRef.current = []
    jitterRef.current.reset()
    stepRef.current = index
    progressRef.current = 0
    startRef.current = performance.now()
    durationRef.current = DURATIONS[index] ?? 0
    collectingRef.current = true
    setStep(index)
    setProgress(0)
    setCollecting(true)
  }

  const goTo = (index: number) => {
    collectingRef.current = false
    setCollecting(false)
    setProgress(0)
    progressRef.current = 0
    stepRef.current = index
    setStep(index)
  }

  const profileDraft = () =>
    buildProfile({
      name,
      bounds: measured.bounds ?? DEFAULT_PROFILE.bounds,
      referenceSpan: measured.span ?? DEFAULT_PROFILE.referenceSpan,
      jitterRmsPx: measured.jitterRmsPx ?? 0,
      pinchRatio: measured.pinchRatio,
      referenceDistanceFt: distanceFt,
      base: {
        ...DEFAULT_PROFILE,
        click: { ...DEFAULT_PROFILE.click, mode: clickMode },
      },
    })

  const save = async () => {
    setSaveState('saving')
    const built = profileDraft()
    try {
      const id = await createConfirmed({
        name: built.name,
        profile: built,
        jitterScore: built.jitter.score,
        distanceFt: built.referenceDistanceFt,
        createdAt: built.createdAt,
      })
      saveActiveProfile(built, id)
      navigate('/track')
    } catch {
      setSaveState('error')
    }
  }

  const ready = pointer.status === 'ready'

  return (
    <div className="flex h-full min-h-0 flex-col bg-background text-foreground">
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_420px]">
        <section className="relative min-h-[280px] overflow-hidden bg-black">
          <video
            ref={videoRef}
            playsInline
            muted
            className="absolute inset-0 h-full w-full object-cover opacity-60"
            style={{ transform: 'scaleX(-1)' }}
          />
          <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />
          <div className="pointer-events-none absolute inset-0 shadow-[inset_0_0_70px_rgba(129,140,248,0.2)]" />

          <div className="absolute left-4 top-4 flex flex-wrap gap-2 text-[11px]">
            <span className="rounded-full border border-border bg-background/75 px-2.5 py-1 backdrop-blur">
              <span className="text-muted-foreground">camera </span>
              <span className={ready ? 'text-success' : 'text-warning'}>{pointer.status}</span>
            </span>
            <span className="rounded-full border border-border bg-background/75 px-2.5 py-1 backdrop-blur">
              <span className="text-muted-foreground">hand </span>
              <span className={handSeen ? 'text-success' : 'text-muted-foreground'}>
                {handSeen ? 'detected' : 'not visible'}
              </span>
            </span>
            <span className="rounded-full border border-border bg-background/75 px-2.5 py-1 backdrop-blur">
              <span className="text-muted-foreground">step </span>
              <span className="text-foreground">
                {step + 1}/{STEP_TITLES.length}
              </span>
            </span>
          </div>

          {collecting ? (
            <div className="absolute inset-x-6 bottom-6">
              <div className="mb-2 flex justify-between text-[11px] text-muted-foreground">
                <span>measuring…</span>
                <span>{Math.round(progress * 100)}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-background/70">
                <div
                  className="h-full rounded-full bg-primary transition-[width] duration-100"
                  style={{ width: `${Math.round(progress * 100)}%` }}
                />
              </div>
            </div>
          ) : null}

          {pointer.status === 'error' ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-background/75 p-6 text-center text-sm text-muted-foreground">
              <p className="max-w-sm">{pointer.error ?? 'Camera unavailable.'}</p>
              <button
                type="button"
                onClick={() => setSimulate(true)}
                className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
              >
                Continue with a simulated hand
              </button>
            </div>
          ) : null}
        </section>

        <aside className="flex min-h-0 flex-col gap-4 overflow-y-auto border-l border-border p-5">
          <ol className="flex flex-wrap gap-1 text-[11px]">
            {STEP_TITLES.map((title, index) => (
              <li
                key={title}
                className={cn(
                  'rounded-full border px-2 py-0.5',
                  index === step
                    ? 'border-primary bg-primary/15 text-primary'
                    : index < step
                      ? 'border-success/40 text-success'
                      : 'border-border text-muted-foreground',
                )}
              >
                {index + 1}. {title}
              </li>
            ))}
          </ol>

          {step === 0 ? (
            <Card title="Before we start">
              <p>
                Stand where you normally use the laptop and keep your hand inside the
                frame. We measure at <em>this</em> distance, so the tracker can size the
                cursor for it later.
              </p>
              <ul className="mt-3 space-y-1 text-xs text-muted-foreground">
                <li>• Good even light on your hand helps more than any setting.</li>
                <li>• If the camera fails, the simulated hand runs the same steps.</li>
              </ul>
              <div className="mt-4 flex flex-wrap gap-2">
                <PrimaryButton disabled={!ready} onClick={() => startStep(1)}>
                  Start measuring
                </PrimaryButton>
                <GhostButton onClick={() => setSimulate((s) => !s)}>
                  {simulate ? 'Use real camera' : 'Use simulated hand'}
                </GhostButton>
              </div>
            </Card>
          ) : null}

          {step === 1 ? (
            <Card title="Sweep the box you can reach">
              <p>
                Point at the screen and move your hand in a wide circle for eight
                seconds — as far left, right, up and down as feels comfortable. Do not
                stretch; this box becomes the edge of your screen.
              </p>
              <Readout
                items={[
                  [
                    'reach box',
                    measured.bounds
                      ? `${Math.round((measured.bounds.maxX - measured.bounds.minX) * 100)}% × ${Math.round(
                          (measured.bounds.maxY - measured.bounds.minY) * 100,
                        )}%`
                      : 'not measured',
                  ],
                  ['hand size', measured.span ? `${(measured.span * 100).toFixed(1)}% of frame` : '—'],
                ]}
              />
              <StepActions
                collecting={collecting}
                hasResult={!!measured.bounds}
                onRedo={() => startStep(1)}
                onBack={() => goTo(0)}
                onNext={() => goTo(2)}
              />
            </Card>
          ) : null}

          {step === 2 ? (
            <Card title="Pinch three or four times">
              <p>
                Pinch your thumb and index finger together, then open your hand. We
                record both gaps and split the difference, so your click threshold is
                yours rather than a number we guessed.
              </p>
              <Readout
                items={[
                  [
                    'pinch threshold',
                    measured.pinchRatio ? `${measured.pinchRatio.toFixed(2)} hand-units` : 'not measured',
                  ],
                  ['samples', `${tightRef.current.length} pinched / ${openRef.current.length} open`],
                ]}
              />
              <StepActions
                collecting={collecting}
                hasResult={!!measured.pinchRatio}
                onRedo={() => startStep(2)}
                onBack={() => goTo(1)}
                onNext={() => goTo(3)}
              />
            </Card>
          ) : null}

          {step === 3 ? (
            <Card title="Hold your hand still">
              <p>
                Point at the centre of the screen and hold as steady as you can for four
                seconds. This measures how much your camera and hand actually shake — it
                sets the smoothing and the deadzone you will use.
              </p>
              <Readout
                items={[
                  [
                    'jitter',
                    measured.jitterRmsPx !== undefined
                      ? `${measured.jitterRmsPx.toFixed(2)} px RMS`
                      : 'not measured',
                  ],
                  [
                    'steadiness',
                    measured.jitterRmsPx !== undefined
                      ? `${Math.round(100 * Math.exp(-measured.jitterRmsPx / 6))}/100`
                      : '—',
                  ],
                ]}
              />
              <StepActions
                collecting={collecting}
                hasResult={measured.jitterRmsPx !== undefined}
                onRedo={() => startStep(3)}
                onBack={() => goTo(2)}
                onNext={() => goTo(4)}
              />
            </Card>
          ) : null}

          {step === 4 ? (
            <Card title="Save this profile">
              <label className="block text-xs text-muted-foreground" htmlFor="profile-name">
                Profile name
              </label>
              <input
                id="profile-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={60}
                className="mt-1 h-10 w-full rounded-lg border border-input bg-background px-3 text-sm text-foreground outline-none focus:border-ring"
              />

              <div className="mt-4">
                <p className="text-xs text-muted-foreground">Your usual distance (for the readout)</p>
                <div className="mt-1 flex items-center gap-2">
                  <GhostButton onClick={() => setDistanceFt((v) => Math.max(1, Math.round((v - 0.5) * 10) / 10))}>
                    −
                  </GhostButton>
                  <span className="w-20 text-center text-sm tabular-nums">{distanceFt.toFixed(1)} ft</span>
                  <GhostButton onClick={() => setDistanceFt((v) => Math.min(15, Math.round((v + 0.5) * 10) / 10))}>
                    +
                  </GhostButton>
                </div>
              </div>

              <div className="mt-4">
                <p className="text-xs text-muted-foreground">Click style</p>
                <div className="mt-1 grid grid-cols-2 gap-2">
                  {(['dwell', 'pinch'] as const).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      data-air-target
                      onClick={() => setClickMode(mode)}
                      className={cn(
                        'min-h-10 rounded-lg border px-2 text-xs font-medium',
                        clickMode === mode
                          ? 'border-primary bg-primary/15 text-primary'
                          : 'border-input text-muted-foreground hover:bg-accent',
                      )}
                    >
                      {mode === 'dwell' ? 'Hold still' : 'Pinch'}
                    </button>
                  ))}
                </div>
              </div>

              <Readout
                items={[
                  ['reach box', measured.bounds ? 'calibrated' : 'default'],
                  ['pinch', measured.pinchRatio ? measured.pinchRatio.toFixed(2) : 'default'],
                  ['jitter', measured.jitterRmsPx !== undefined ? `${measured.jitterRmsPx.toFixed(2)} px` : 'default'],
                  ['smoothing', `${profileDraft().smoothing.minCutoff.toFixed(2)} cutoff`],
                ]}
              />

              <div className="mt-4 flex flex-wrap gap-2">
                <PrimaryButton onClick={save} disabled={saveState === 'saving'}>
                  {saveState === 'saving' ? 'Saving…' : 'Save and open tracker'}
                </PrimaryButton>
                <GhostButton
                  onClick={() => {
                    saveActiveProfile(profileDraft(), null)
                    navigate('/track')
                  }}
                >
                  Use without saving
                </GhostButton>
                <GhostButton onClick={() => goTo(3)}>Back</GhostButton>
              </div>
              {saveState === 'error' ? (
                <p className="mt-2 text-xs text-warning">
                  Could not reach DeepSpace. &quot;Use without saving&quot; keeps the profile
                  in this browser.
                </p>
              ) : null}
            </Card>
          ) : null}
        </aside>
      </div>

      <AirCursor innerRef={cursorRef} />
    </div>
  )
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-card p-5 text-sm">
      <h2 className="text-base font-semibold">{title}</h2>
      <div className="mt-2 space-y-2 text-muted-foreground">{children}</div>
    </div>
  )
}

function Readout({ items }: { items: Array<[string, string]> }) {
  return (
    <dl className="mt-4 grid grid-cols-2 gap-2 rounded-lg border border-border bg-background/40 p-3 text-xs">
      {items.map(([label, value]) => (
        <div key={label}>
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="mt-0.5 font-medium text-foreground">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

function StepActions({
  collecting,
  hasResult,
  onRedo,
  onBack,
  onNext,
}: {
  collecting: boolean
  hasResult: boolean
  onRedo: () => void
  onBack: () => void
  onNext: () => void
}) {
  return (
    <div className="mt-4 flex flex-wrap gap-2">
      <PrimaryButton onClick={onRedo} disabled={collecting}>
        {hasResult ? 'Measure again' : 'Start measuring'}
      </PrimaryButton>
      <GhostButton onClick={onBack} disabled={collecting}>
        Back
      </GhostButton>
      <GhostButton onClick={onNext} disabled={collecting || !hasResult}>
        Next
      </GhostButton>
    </div>
  )
}

function PrimaryButton({
  children,
  onClick,
  disabled,
}: {
  children: React.ReactNode
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      data-air-target
      onClick={onClick}
      disabled={disabled}
      className="min-h-11 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-40"
    >
      {children}
    </button>
  )
}

function GhostButton({
  children,
  onClick,
  disabled,
}: {
  children: React.ReactNode
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      data-air-target
      onClick={onClick}
      disabled={disabled}
      className="min-h-11 rounded-lg border border-input px-4 text-sm font-medium hover:bg-accent disabled:opacity-40"
    >
      {children}
    </button>
  )
}
