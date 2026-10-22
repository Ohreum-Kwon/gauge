import { Link, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth'
import LabelPage from './pages/LabelPage'
import LoginPage from './pages/LoginPage'
import ProjectPage from './pages/ProjectPage'
import ProjectsPage from './pages/ProjectsPage'
import type { Role } from './types'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<SignedInLayout />}>
        <Route index element={<Navigate to="/projects" replace />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route element={<RequireRole role="admin" />}>
          <Route path="/projects/:projectId" element={<ProjectPage />} />
        </Route>
        <Route element={<RequireRole role="labeler" />}>
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
        <span className="muted">
          {user.email} · {user.role}
        </span>
        <button type="button" className="link" onClick={logout}>
          Sign out
        </button>
      </header>
      <main className="page">
        <Outlet />
      </main>
    </>
  )
}

function RequireRole({ role }: { role: Role }) {
  const { user } = useAuth()
  return user?.role === role ? <Outlet /> : <Navigate to="/projects" replace />
}
