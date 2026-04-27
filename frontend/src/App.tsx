import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './core/AuthContext'

const Login         = lazy(() => import('./views/Login'))
const StoreLayout   = lazy(() => import('./views/fsr/store/Layout'))
const Overview      = lazy(() => import('./views/fsr/store/Overview'))
const CallHistory   = lazy(() => import('./views/fsr/store/CallHistory'))
const Reservations  = lazy(() => import('./views/fsr/store/Reservations'))
const Analytics     = lazy(() => import('./views/fsr/store/Analytics'))
const Settings      = lazy(() => import('./views/fsr/store/Settings'))
const CctvOverlay   = lazy(() => import('./views/fsr/store/CctvOverlay'))

// Agency dashboard (에이전시 대시보드)
const AgencyLayout      = lazy(() => import('./views/agency/Layout'))
const AgencyOverview    = lazy(() => import('./views/agency/Overview'))
const AgencyStoreDetail = lazy(() => import('./views/agency/StoreDetail'))

// Stubs — "Coming Soon" placeholders until each page is built
const ComingSoon = ({ title }: { title: string }) => (
  <div style={{ padding: 32, color: '#64748b', fontSize: 18 }}>
    <strong>{title}</strong> — Coming Soon
  </div>
)

function RequireAuth({ children }: { children: JSX.Element }) {
  const { token } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  return children
}

function homeRedirect(token: string | null, role: string | null) {
  if (!token) return '/login'
  return role === 'AGENCY' ? '/agency/overview' : '/fsr/store/overview'
}

function AppRoutes() {
  const { token, role } = useAuth()
  const home = homeRedirect(token, role)

  return (
    <Suspense fallback={<div style={{ padding: 32, color: '#64748b' }}>Loading...</div>}>
      <Routes>
        {/* Auth */}
        <Route path="/login" element={token ? <Navigate to={home} replace /> : <Login />} />

        {/* Agency routes (에이전시 라우트) */}
        <Route
          path="/agency"
          element={
            <RequireAuth>
              <AgencyLayout />
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="overview" replace />} />
          <Route path="overview"         element={<AgencyOverview />} />
          <Route path="store/:storeId"   element={<AgencyStoreDetail />} />
        </Route>

        {/* Backward compat: old /agency/dashboard → /agency/overview */}
        <Route path="/agency/dashboard" element={<Navigate to="/agency/overview" replace />} />

        {/* FSR Store (store owner mode — store owner 모드) */}
        <Route
          path="/fsr/store"
          element={
            <RequireAuth>
              <StoreLayout />
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="overview" replace />} />
          <Route path="overview"           element={<Overview />} />
          <Route path="ai-voice-bot"       element={<ComingSoon title="AI Voice Bot" />} />
          <Route path="call-history"       element={<CallHistory />} />
          <Route path="reservations"       element={<Reservations />} />
          <Route path="analytics"          element={<Analytics />} />
          <Route path="settings"           element={<Settings />} />
          <Route path="security/solink"    element={<CctvOverlay />} />
          <Route path="security/theft"     element={<ComingSoon title="Prevent Theft" />} />
        </Route>

        {/* Root → redirect based on auth + role */}
        <Route path="/" element={<Navigate to={home} replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AppRoutes />
      </BrowserRouter>
    </AuthProvider>
  )
}
