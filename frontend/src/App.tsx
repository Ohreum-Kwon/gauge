import { lazy, Suspense } from 'react'
import { Link, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth'
import AuditPage from './pages/AuditPage'
import LabelPage from './pages/LabelPage'
import LoginPage from './pages/LoginPage'
import ProjectPage from './pages/ProjectPage'
import ProjectsPage from './pages/ProjectsPage'
import ReviewPage from './pages/ReviewPage'
import type { Role } from './types'

// The charting library is large, so only staff who open a dashboard download it.
const QualityPage = lazy(() => import('./pages/QualityPage'))

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<SignedInLayout />}>
        <Route index element={<Navigate to="/projects" replace />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route element={<RequireRole roles={['admin']} />}>
          <Route path="/projects/:projectId" element={<ProjectPage />} />
          <Route path="/audit" element={<AuditPage />} />
        </Route>
        <Route element={<RequireRole roles={['admin', 'reviewer']} />}>
          <Route path="/projects/:projectId/quality" element={<QualityPage />} />
          <Route path="/projects/:projectId/review" element={<ReviewPage />} />
        </Route>
        <Route element={<RequireRole roles={['labeler']} />}>
          <Route path="/projects/:projectId/label" element={<LabelPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

function SignedInLayout() {
  const { user, loading, logout } = useAuth()
  if (loading) return <p className="page muted">Loading…</p>
  if (!user) return <Navigate to="/login" replace />

  return (
    <>
      <header className="topbar">
        <Link to="/projects" className="brand">
          Gauge
        </Link>
        {user.role === 'admin' && <Link to="/audit">Audit log</Link>}
        <span className="muted">
          {user.email} · {user.role}
        </span>
        <button type="button" className="link" onClick={logout}>
          Sign out
        </button>
      </header>
      <main className="page">
        <Suspense fallback={<p className="muted">Loading…</p>}>
          <Outlet />
        </Suspense>
      </main>
    </>
  )
}

function RequireRole({ roles }: { roles: Role[] }) {
  const { user } = useAuth()
  return user && roles.includes(user.role) ? <Outlet /> : <Navigate to="/projects" replace />
}
