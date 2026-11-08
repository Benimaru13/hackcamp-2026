/**
 * Dashboard: the active profile, the profiles saved in DeepSpace, and the way
 * back into the tracker.
 *
 * The saved list is a live `useQuery` — records stream over the app's records
 * socket, so a profile saved on another laptop appears here without a refresh.
 */

import { Link } from 'react-router-dom'
import { useMutations, useQuery } from 'deepspace'
import {
  adoptProfile,
  clearActiveProfile,
  useActiveProfile,
} from '@/lib/airtrack/store'
import type { CalibrationProfileRecord } from '@/schemas/profiles-schema'

const CLICK_LABEL: Record<string, string> = {
  dwell: 'hold still to click',
  pinch: 'pinch to click',
}

export default function HomePage() {
  const { profile, recordId } = useActiveProfile()
  const { records, status } = useQuery<CalibrationProfileRecord>('calibration_profiles', {
    orderBy: 'createdAt',
    orderDir: 'desc',
    limit: 20,
  })
  const { remove } = useMutations<CalibrationProfileRecord>('calibration_profiles')

  return (
    <div className="mx-auto max-w-5xl px-6 py-10 text-foreground">
      <p className="text-xs uppercase tracking-[0.28em] text-muted-foreground">AirTrack</p>
      <h1 className="mt-2 text-3xl font-bold tracking-tight">Your air control panel</h1>
      <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
        Calibrate once, then control the tracker with your hand. The profile stores the
        reach box you swept, your pinch distance, and the smoothing that matches your
        hand&apos;s jitter.
      </p>

      <div className="mt-8 grid gap-4 md:grid-cols-[1.2fr_1fr]">
        <section className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold">Active profile</h2>
              <p className="mt-1 text-2xl font-semibold tracking-tight">{profile.name}</p>
            </div>
            <span className="rounded-full border border-success/40 bg-success/10 px-3 py-1 text-xs text-success">
              {profile.jitter.score}/100 steady
            </span>
          </div>

          <dl className="mt-5 grid grid-cols-2 gap-3 text-sm">
            <Stat label="Distance" value={`${profile.referenceDistanceFt.toFixed(1)} ft`} />
            <Stat label="Clicks" value={CLICK_LABEL[profile.click.mode]} />
            <Stat
              label="Reach box"
              value={`${Math.round((profile.bounds.maxX - profile.bounds.minX) * 100)}% wide`}
            />
            <Stat label="Cursor base" value={`${Math.round(profile.cursor.basePx)} px`} />
            <Stat label="Smoothing" value={`${profile.smoothing.minCutoff.toFixed(2)} cutoff`} />
            <Stat label="Sensitivity" value={`${profile.sensitivity.toFixed(1)}x`} />
          </dl>

          <div className="mt-6 flex flex-wrap gap-2">
            <Link
              to="/track"
              className="inline-flex h-10 items-center rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:opacity-90"
            >
              Open tracker
            </Link>
            <Link
              to="/calibrate"
              className="inline-flex h-10 items-center rounded-lg border border-input px-4 text-sm font-medium hover:bg-accent"
            >
              {recordId ? 'Recalibrate' : 'Run the calibrator'}
            </Link>
            <button
              type="button"
              onClick={() => clearActiveProfile()}
              className="inline-flex h-10 items-center rounded-lg px-4 text-sm text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              Reset to defaults
            </button>
          </div>
        </section>

        <section className="rounded-xl border border-border bg-card p-5">
          <h2 className="text-sm font-semibold">How the loop works</h2>
          <ol className="mt-3 space-y-3 text-sm text-muted-foreground">
            <li>
              <span className="text-foreground">1. Calibrate.</span> Sweep your hand
              through the box you can reach comfortably, pinch three times, then hold
              still for four seconds.
            </li>
            <li>
              <span className="text-foreground">2. Arm.</span> In the tracker, hold an
              open palm for half a second. A fist, or losing your hand, releases control.
            </li>
            <li>
              <span className="text-foreground">3. Point.</span> The cursor grows as you
              step back, and holding still (or pinching) clicks whatever it is over.
            </li>
          </ol>
        </section>
      </div>

      <section className="mt-8">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-sm font-semibold">Profiles saved in DeepSpace</h2>
          <span className="text-xs text-muted-foreground">
            {status === 'loading' ? 'syncing…' : `${records.length} saved`}
          </span>
        </div>

        {records.length === 0 ? (
          <div className="mt-3 rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
            No saved profiles yet. Run the calibrator and save one — it will sync to
            every device signed into this app.
          </div>
        ) : (
          <ul className="mt-3 divide-y divide-border overflow-hidden rounded-xl border border-border">
            {records.map((record) => {
              const saved = record.data.profile
              const active = record.recordId === recordId
              return (
                <li
                  key={record.recordId}
                  className="flex flex-wrap items-center gap-3 bg-card px-4 py-3 text-sm"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">
                      {record.data.name}
                      {active ? (
                        <span className="ml-2 rounded-full bg-primary/15 px-2 py-0.5 text-[10px] uppercase tracking-wide text-primary">
                          active
                        </span>
                      ) : null}
                    </p>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {Math.round(record.data.jitterScore)}/100 steady ·{' '}
                      {Number(record.data.distanceFt).toFixed(1)} ft ·{' '}
                      {saved ? CLICK_LABEL[saved.click?.mode ?? 'dwell'] : 'dwell'}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => adoptProfile(record.data.profile, record.recordId)}
                    className="rounded-md border border-input px-3 py-1.5 text-xs hover:bg-accent"
                  >
                    Use
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      void remove(record.recordId)
                      if (record.recordId === recordId) clearActiveProfile()
                    }}
                    className="rounded-md px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
                  >
                    Delete
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </section>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-sm text-foreground">{value}</dd>
    </div>
  )
}
