/**
 * The tracker: the air-controlled surface.
 *
 * Everything you can act on is a `[data-air-target]` element, so a dwell (or a
 * pinch) lands a real DOM click on it. That is what makes this usable with no
 * keyboard at all — including the settings, which are steppers rather than
 * sliders or text fields.
 */

import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Pause, Play, SkipBack, SkipForward, Volume1, Volume2 } from 'lucide-react'
import { useMutations } from 'deepspace'
import { AirCursor } from '@/components/airtrack/AirCursor'
import type { CalibrationProfile } from '@/lib/airtrack/calibration'
import type { AirState } from '@/lib/airtrack/engine'
import { saveActiveProfile, useActiveProfile } from '@/lib/airtrack/store'
import { useAirPointer } from '@/lib/airtrack/useAirPointer'
import { cn } from '@/lib/utils'
import type { CalibrationProfileRecord } from '@/schemas/profiles-schema'

const TRACKS = ['Dinner is ready', 'Kitchen radio', 'Podcast · ep. 12']

export default function TrackPage() {
  const active = useActiveProfile()
  const [profile, setProfile] = useState<CalibrationProfile>(active.profile)
  const [recordId, setRecordId] = useState<string | null>(active.recordId)
  const [simulate, setSimulate] = useState(false)
  const [hud, setHud] = useState<AirState | null>(null)
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')

  const [playing, setPlaying] = useState(false)
  const [trackIndex, setTrackIndex] = useState(0)
  const [volume, setVolume] = useState(40)
  const [log, setLog] = useState<string[]>([])

  const videoRef = useRef<HTMLVideoElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const cursorRef = useRef<HTMLDivElement | null>(null)
  const activityRef = useRef<HTMLDivElement | null>(null)

  const { createConfirmed, putConfirmed } = useMutations<CalibrationProfileRecord>(
    'calibration_profiles',
  )

  const pointer = useAirPointer({
    simulate,
    profile,
    videoRef,
    canvasRef,
    cursorRef,
    onHud: setHud,
    onScroll: (dy) => activityRef.current?.scrollBy({ top: dy }),
  })

  const note = (text: string) =>
    setLog((prev) =>
      [`${new Date().toLocaleTimeString([], { hour12: false })} · ${text}`, ...prev].slice(0, 30),
    )

  const update = (patch: Partial<CalibrationProfile>) => {
    setProfile((prev) => {
      const next = { ...prev, ...patch }
      saveActiveProfile(next, recordId)
      return next
    })
  }

  const adjust = (delta: number, current: number, lo: number, hi: number, decimals = 0) => {
    const f = 10 ** decimals
    return Math.round(Math.min(hi, Math.max(lo, current + delta)) * f) / f
  }

  const saveToDeepSpace = async () => {
    setSaveState('saving')
    const payload: CalibrationProfileRecord = {
      name: profile.name,
      profile,
      jitterScore: profile.jitter.score,
      distanceFt: profile.referenceDistanceFt,
      createdAt: profile.createdAt || new Date().toISOString(),
    }
    try {
      if (recordId) {
        await putConfirmed(recordId, payload)
      } else {
        const id = await createConfirmed(payload)
        setRecordId(id)
        saveActiveProfile(profile, id)
      }
      setSaveState('saved')
      note('profile saved to DeepSpace')
    } catch {
      setSaveState('error')
      note('could not save profile — check the connection')
    }
  }

  const activeState = hud?.state === 'active'

  return (
    <div className="relative flex h-full min-h-0 flex-col bg-background text-foreground">
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_380px]">
        {/* ---------------------------------------------------------- stage */}
        <section className="relative min-h-[300px] overflow-hidden bg-black">
          <video
            ref={videoRef}
            playsInline
            muted
            className="absolute inset-0 h-full w-full object-cover opacity-60"
            style={{ transform: 'scaleX(-1)' }}
          />
          <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />

          <div
            className={cn(
              'pointer-events-none absolute inset-0 transition-shadow duration-500',
              activeState
                ? 'shadow-[inset_0_0_80px_rgba(16,185,129,0.5)]'
                : 'shadow-[inset_0_0_60px_rgba(129,140,248,0.18)]',
            )}
          />

          <div className="absolute left-4 top-4 flex max-w-[calc(100%-2rem)] flex-wrap gap-2">
            <Pill label="state" value={activeState ? 'active' : 'armed'} tone={activeState ? 'success' : 'muted'} />
            <Pill label="pose" value={hud?.pose ?? '—'} />
            <Pill label="distance" value={hud ? `${hud.distanceFeet.toFixed(1)} ft` : '—'} />
            <Pill
              label="cursor"
              value={`${Math.round(hud?.cursor?.radius ?? profile.cursor.basePx)} px`}
            />
            <Pill label="jitter" value={hud ? `${hud.jitter.score}/100` : '—'} tone={jitterTone(hud)} />
          </div>

          <div className="absolute inset-x-4 bottom-4 space-y-2">
            {hud?.state === 'armed' && hud.armProgress > 0 ? (
              <div className="h-1.5 overflow-hidden rounded-full bg-background/60">
                <div
                  className="h-full rounded-full bg-primary transition-[width] duration-75"
                  style={{ width: `${Math.round(hud.armProgress * 100)}%` }}
                />
              </div>
            ) : null}
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-background/80 px-3 py-2 text-sm backdrop-blur">
              <span className="flex-1 text-muted-foreground">
                {hud?.hint ?? 'waiting for the camera…'}
              </span>
              <span className="text-xs text-muted-foreground">
                {hud?.handDetected ? 'hand tracked' : 'no hand'}
              </span>
            </div>
          </div>

          {pointer.status === 'loading' ? (
            <StageNotice text="Starting the camera and the hand model…" />
          ) : null}
          {pointer.status === 'error' ? (
            <StageNotice
              text={pointer.error ?? 'Camera unavailable.'}
              action={
                <button
                  type="button"
                  onClick={() => setSimulate(true)}
                  className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
                >
                  Use simulate mode
                </button>
              }
            />
          ) : null}
          {pointer.status === 'ready' && !hud?.handDetected ? (
            <StageNotice text="Hold your hand up to the camera, palm out." />
          ) : null}
          {simulate ? (
            <div className="absolute right-4 top-4 rounded-full border border-warning/40 bg-warning/10 px-3 py-1 text-xs text-warning">
              simulate mode
            </div>
          ) : null}
        </section>

        {/* --------------------------------------------------------- controls */}
        <aside className="flex min-h-0 flex-col gap-4 overflow-y-auto border-l border-border p-4">
          <div className="flex gap-2">
            <button
              type="button"
              data-air-target
              onClick={() => pointer.engineRef.current?.arm(performance.now())}
              className="min-h-11 flex-1 rounded-lg bg-primary/15 px-3 text-sm font-medium text-primary hover:bg-primary/25"
            >
              Take control
            </button>
            <button
              type="button"
              data-air-target
              onClick={() => pointer.engineRef.current?.disarm()}
              className="min-h-11 flex-1 rounded-lg border border-input px-3 text-sm font-medium hover:bg-accent"
            >
              Stop (fist)
            </button>
          </div>

          <div className="rounded-xl border border-border bg-card p-3">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Now playing</p>
            <p className="mt-1 text-sm font-medium">{TRACKS[trackIndex]}</p>
            <p className="text-xs text-muted-foreground">
              {playing ? '▶ playing' : 'paused'} · volume {volume}%
            </p>
            <div className="mt-3 grid grid-cols-3 gap-2">
              <ActionTile
                label="Previous"
                icon={<SkipBack aria-hidden />}
                onClick={() => {
                  setTrackIndex((i) => (i - 1 + TRACKS.length) % TRACKS.length)
                  note('previous track')
                }}
              />
              <ActionTile
                label={playing ? 'Pause' : 'Play'}
                icon={playing ? <Pause aria-hidden /> : <Play aria-hidden />}
                onClick={() => {
                  setPlaying((p) => !p)
                  note(playing ? 'pause' : 'play')
                }}
              />
              <ActionTile
                label="Next"
                icon={<SkipForward aria-hidden />}
                onClick={() => {
                  setTrackIndex((i) => (i + 1) % TRACKS.length)
                  note('next track')
                }}
              />
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2">
              <ActionTile
                label="Volume up"
                icon={<Volume2 aria-hidden />}
                onClick={() => {
                  setVolume((v) => Math.min(100, v + 10))
                  note('volume up')
                }}
              />
              <ActionTile
                label="Volume down"
                icon={<Volume1 aria-hidden />}
                onClick={() => {
                  setVolume((v) => Math.max(0, v - 10))
                  note('volume down')
                }}
              />
            </div>
          </div>

          <div className="rounded-xl border border-border bg-card p-3">
            <div className="flex items-baseline justify-between">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Activity</p>
              <span className="text-[10px] text-muted-foreground">two fingers to scroll</span>
            </div>
            <div ref={activityRef} className="mt-2 h-32 space-y-1 overflow-y-auto pr-1 text-xs">
              {log.length === 0 ? (
                <p className="text-muted-foreground">
                  Nothing yet. Hold your palm up, then aim at a tile and hold still.
                </p>
              ) : (
                log.map((entry, index) => (
                  <p key={`${entry}-${index}`} className="text-muted-foreground">
                    {entry}
                  </p>
                ))
              )}
            </div>
          </div>

          <div className="rounded-xl border border-border bg-card p-3">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Tune it</p>
            <Stepper
              label="Cursor size"
              value={`${Math.round(profile.cursor.basePx)} px`}
              hint="the ring grows with distance"
              onDec={() => update({ cursor: { ...profile.cursor, basePx: adjust(-2, profile.cursor.basePx, 8, 44) } })}
              onInc={() => update({ cursor: { ...profile.cursor, basePx: adjust(2, profile.cursor.basePx, 8, 44) } })}
            />
            <Stepper
              label="Sensitivity"
              value={`${profile.sensitivity.toFixed(1)}x`}
              hint="how much hand travel fills the screen"
              onDec={() => update({ sensitivity: adjust(-0.1, profile.sensitivity, 0.5, 2, 1) })}
              onInc={() => update({ sensitivity: adjust(0.1, profile.sensitivity, 0.5, 2, 1) })}
            />
            <Stepper
              label="Steadiness"
              value={profile.smoothing.minCutoff.toFixed(2)}
              hint="lower = calmer, higher = snappier"
              onDec={() => update({ smoothing: { ...profile.smoothing, minCutoff: adjust(-0.1, profile.smoothing.minCutoff, 0.4, 2, 1) } })}
              onInc={() => update({ smoothing: { ...profile.smoothing, minCutoff: adjust(0.1, profile.smoothing.minCutoff, 0.4, 2, 1) } })}
            />
            <Stepper
              label="Dwell time"
              value={`${profile.click.dwellSeconds.toFixed(1)} s`}
              hint="how long a still hand clicks"
              onDec={() => update({ click: { ...profile.click, dwellSeconds: adjust(-0.2, profile.click.dwellSeconds, 0.6, 3, 1) } })}
              onInc={() => update({ click: { ...profile.click, dwellSeconds: adjust(0.2, profile.click.dwellSeconds, 0.6, 3, 1) } })}
            />

            <div className="mt-3">
              <p className="text-xs text-muted-foreground">Click style</p>
              <div className="mt-1 grid grid-cols-2 gap-2">
                {(['dwell', 'pinch'] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    data-air-target
                    onClick={() => update({ click: { ...profile.click, mode } })}
                    className={cn(
                      'min-h-10 rounded-lg border px-2 text-xs font-medium',
                      profile.click.mode === mode
                        ? 'border-primary bg-primary/15 text-primary'
                        : 'border-input text-muted-foreground hover:bg-accent',
                    )}
                  >
                    {mode === 'dwell' ? 'Hold still' : 'Pinch'}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="rounded-xl border border-border bg-card p-3">
            <div className="flex items-center justify-between gap-2">
              <button
                type="button"
                data-air-target
                onClick={saveToDeepSpace}
                className="min-h-10 flex-1 rounded-lg bg-primary/15 px-3 text-xs font-medium text-primary hover:bg-primary/25"
              >
                {saveState === 'saving' ? 'Saving…' : 'Save to DeepSpace'}
              </button>
              <button
                type="button"
                data-air-target
                onClick={() => setSimulate((s) => !s)}
                className={cn(
                  'min-h-10 rounded-lg border px-3 text-xs',
                  simulate ? 'border-warning/50 text-warning' : 'border-input text-muted-foreground',
                )}
              >
                {simulate ? 'Simulated' : 'Simulate'}
              </button>
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">
              {saveState === 'saved'
                ? 'Saved. It syncs to your other devices.'
                : saveState === 'error'
                  ? 'Save failed — the profile still applies in this session.'
                  : `Profile: ${profile.name}${recordId ? '' : ' (not saved yet)'}`}
            </p>
            <Link
              to="/calibrate"
              className="mt-2 block text-center text-[11px] text-primary underline-offset-4 hover:underline"
            >
              Recalibrate instead
            </Link>
          </div>
        </aside>
      </div>

      <AirCursor innerRef={cursorRef} />
    </div>
  )
}

function jitterTone(hud: AirState | null): 'success' | 'warning' | 'muted' {
  if (!hud) return 'muted'
  if (hud.jitter.score >= 80) return 'success'
  if (hud.jitter.score >= 50) return 'warning'
  return 'muted'
}

function Pill({
  label,
  value,
  tone = 'muted',
}: {
  label: string
  value: string
  tone?: 'muted' | 'success' | 'warning'
}) {
  return (
    <span className="rounded-full border border-border bg-background/75 px-2.5 py-1 text-[11px] backdrop-blur">
      <span className="text-muted-foreground">{label} </span>
      <span
        className={cn(
          'font-medium',
          tone === 'success' ? 'text-success' : tone === 'warning' ? 'text-warning' : 'text-foreground',
        )}
      >
        {value}
      </span>
    </span>
  )
}

function StageNotice({ text, action }: { text: string; action?: React.ReactNode }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-background/70 p-6 text-center text-sm text-muted-foreground">
      <p className="max-w-sm">{text}</p>
      {action}
    </div>
  )
}

function ActionTile({
  label,
  icon,
  onClick,
}: {
  label: string
  icon: React.ReactNode
  onClick: () => void
}) {
  return (
    <button
      type="button"
      data-air-target
      onClick={onClick}
      className="flex min-h-20 flex-col items-center justify-center gap-1 rounded-lg border border-border bg-background/60 px-2 py-2 text-[11px] text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground"
    >
      <span className="text-foreground [&_svg]:size-5">{icon}</span>
      {label}
    </button>
  )
}

function Stepper({
  label,
  value,
  hint,
  onDec,
  onInc,
}: {
  label: string
  value: string
  hint: string
  onDec: () => void
  onInc: () => void
}) {
  return (
    <div className="mt-3 flex items-center gap-2">
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs text-foreground">{label}</p>
        <p className="truncate text-[10px] text-muted-foreground">{hint}</p>
      </div>
      <button
        type="button"
        data-air-target
        aria-label={`Decrease ${label}`}
        onClick={onDec}
        className="size-9 rounded-lg border border-input text-sm hover:bg-accent"
      >
        −
      </button>
      <span className="w-14 text-center text-xs tabular-nums text-foreground">{value}</span>
      <button
        type="button"
        data-air-target
        aria-label={`Increase ${label}`}
        onClick={onInc}
        className="size-9 rounded-lg border border-input text-sm hover:bg-accent"
      >
        +
      </button>
    </div>
  )
}
