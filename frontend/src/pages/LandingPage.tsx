import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import DriftIllustration from '../components/DriftIllustration'

const DEMO_PASSWORD = 'gauge-demo'
// Created by `python -m app.simulate`; the landing page opens its quality dashboard.
const DRIFT_PROJECT = 'Simulated labelers (drift demo)'
const DRIFTER = 'sim-drifter@gauge.dev'
const REPO = 'https://github.com/Ohreum-Kwon/gauge'

interface Tour {
  key: string
  title: string
  body: string
  email: string
  /** Where to go once signed in. Resolved after sign-in because it can need the API. */
  destination: () => Promise<string>
}

async function driftDashboard(): Promise<string> {
  const project = (await api.projects()).find((p) => p.name === DRIFT_PROJECT)
  return project
    ? `/projects/${project.id}/quality?labeler=${encodeURIComponent(DRIFTER)}`
    : '/projects'
}

const TOURS: Tour[] = [
  {
    key: 'drift',
    title: 'Catch a drifting labeler',
    body: 'A simulated labeler is 95% accurate for five days, then 60%. See the control chart flag them on day 6.',
    email: 'reviewer@gauge.dev',
    destination: driftDashboard,
  },
  {
    key: 'panel',
    title: 'Watch a display line drift',
    body: 'The same statistics on panel test data: an ageing backlight and a bad TFT lot, caught on X̄/R and EWMA charts.',
    email: 'reviewer@gauge.dev',
    destination: async () => '/panel-line',
  },
  {
    key: 'label',
    title: 'Label images yourself',
    body: 'Work through a CIFAR-10 queue as a labeler. Some items are hidden gold questions you are graded on.',
    email: 'labeler1@gauge.dev',
    destination: async () => '/projects',
  },
]

export default function LandingPage() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function start(tour: Tour) {
    setBusy(tour.key)
    setError(null)
    try {
      if (user?.email !== tour.email) await login(tour.email, DEMO_PASSWORD)
      navigate(await tour.destination())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Sign-in failed')
      setBusy(null)
    }
  }

  return (
    <div className="landing">
      <header className="landing-nav">
        <span className="brand">Gauge</span>
        <a href={REPO}>GitHub</a>
        {user ? <Link to="/projects">Open the app</Link> : <Link to="/login">Sign in</Link>}
      </header>

      <section className="hero">
        <div>
          <h1>Catch a bad labeler before their labels reach your dataset.</h1>
          <p className="lede">
            Gauge is a data-labeling platform that watches labeler quality the way a factory watches
            a production line: hidden gold questions, agreement between labelers, and a control
            chart for every person.
          </p>
        </div>
        <DriftIllustration />
      </section>

      <section aria-labelledby="tours-heading">
        <h2 id="tours-heading">Try it, no sign-up</h2>
        <div className="tours">
          {TOURS.map((tour) => (
            <button
              key={tour.key}
              type="button"
              className="tour card"
              disabled={busy !== null}
              onClick={() => void start(tour)}
            >
              <strong>{tour.title}</strong>
              <span className="muted">{tour.body}</span>
              <span className="tour-go">{busy === tour.key ? 'Opening…' : 'Open →'}</span>
            </button>
          ))}
        </div>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
      </section>

      <section className="how" aria-labelledby="how-heading">
        <h2 id="how-heading">How it works</h2>
        <ol className="steps">
          <li className="card">
            <strong>Measure</strong>
            <span className="muted">
              Gold questions with known answers are mixed into every queue, so accuracy is sampled
              without the labeler knowing. Some items go to several people to measure agreement
              (Fleiss' and Cohen's kappa).
            </span>
          </li>
          <li className="card">
            <strong>Chart</strong>
            <span className="muted">
              Each labeler's daily error rate goes on a p-chart with 3σ limits around the project's
              target. The Western Electric rules flag a drift, a jump, or someone who was never
              good.
            </span>
          </li>
          <li className="card">
            <strong>Act</strong>
            <span className="muted">
              Labels from an out-of-control day stop counting. Only items the trusted labels can't
              settle go to a reviewer, and every decision lands in an audit log.
            </span>
          </li>
        </ol>
      </section>

      <footer className="landing-foot muted">
        FastAPI, Postgres, React and TypeScript, tested in CI against real Postgres.{' '}
        <a href={`${REPO}#design-notes`}>Design notes</a> · <a href="/api/docs">API docs</a> ·{' '}
        <a href={REPO}>Source</a>
      </footer>
    </div>
  )
}
