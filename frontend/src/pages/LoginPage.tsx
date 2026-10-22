import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../auth'

// Accounts created by `python -m app.seed`, so visitors can try each role in one click.
const DEMO_ACCOUNTS = [
  { label: 'Admin', email: 'admin@gauge.dev' },
  { label: 'Labeler', email: 'labeler1@gauge.dev' },
  { label: 'Reviewer', email: 'reviewer@gauge.dev' },
]
const DEMO_PASSWORD = 'gauge-demo'

export default function LoginPage() {
  const { user, login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to="/projects" replace />

  async function signIn(emailToUse: string, passwordToUse: string) {
    setBusy(true)
    setError(null)
    try {
      await login(emailToUse, passwordToUse)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Sign-in failed')
    } finally {
      setBusy(false)
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    void signIn(email, password)
  }

  return (
    <main className="login">
      <h1>Gauge</h1>
      <p className="muted">Data labeling with statistical quality control.</p>
      <form onSubmit={onSubmit} className="card stack">
        <label>
          Email
          <input
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <button type="submit" disabled={busy}>
          Sign in
        </button>
      </form>
      <div className="demo">
        <span className="muted">Try a demo account:</span>
        {DEMO_ACCOUNTS.map((account) => (
          <button
            key={account.email}
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => void signIn(account.email, DEMO_PASSWORD)}
          >
            {account.label}
          </button>
        ))}
      </div>
    </main>
  )
}
