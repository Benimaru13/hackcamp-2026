/**
 * Landing page — static on purpose: no auth fetch, no records socket, so it
 * loads instantly and prerenders to real HTML for crawlers.
 */

import { Link } from 'react-router-dom'
import { Seo } from '../components/Seo'
import { APP_NAME } from '../constants'
import { seo } from '../seo'

const STEPS = [
  {
    title: 'Calibrates to you',
    body: 'A two-minute wizard measures the box you can comfortably reach, your pinch distance and how steady your hand is. Those numbers become your profile.',
  },
  {
    title: 'Jitter-aware, not just smoothed',
    body: 'The steady-hand measurement sets the smoothing and the deadzone, so a shaky hand stops dragging the pointer without making a steady hand feel laggy.',
  },
  {
    title: 'Distance-adaptive cursor',
    body: 'The cursor ring grows as you step back, so it stays visible and easy to aim at from the far side of the room.',
  },
]

export default function Landing() {
  return (
    <>
      <Seo {...seo} path="/" />
      <div
        data-testid="static-landing"
        className="flex min-h-screen flex-col items-center justify-center px-6 py-20 text-center"
      >
        <p className="mb-3 text-sm uppercase tracking-[0.3em] text-muted-foreground">{APP_NAME}</p>
        <h1 className="mb-5 max-w-3xl text-4xl font-bold tracking-tight text-foreground sm:text-6xl">
          Your hand is the mouse.
        </h1>
        <p className="mb-10 max-w-xl text-base text-muted-foreground">
          Point to move, hold still to click, fist to stop. Built for wet hands, full
          hands, and the far side of the room — with a cursor that adapts to your
          distance and your shake.
        </p>

        <Link
          to="/home"
          className="inline-flex items-center gap-2 rounded-full bg-primary px-6 py-3 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90"
        >
          Open the tracker
        </Link>

        <div className="mt-16 grid max-w-4xl gap-4 text-left sm:grid-cols-3">
          {STEPS.map((step) => (
            <div key={step.title} className="rounded-xl border border-border bg-card p-5">
              <h2 className="mb-2 text-sm font-semibold text-foreground">{step.title}</h2>
              <p className="text-sm leading-relaxed text-muted-foreground">{step.body}</p>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
