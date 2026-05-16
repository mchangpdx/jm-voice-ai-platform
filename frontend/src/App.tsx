import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth, UserRole } from './core/AuthContext'

const Login         = lazy(() => import('./views/Login'))
const StoreLayout   = lazy(() => import('./views/fsr/store/Layout'))
const Overview      = lazy(() => import('./views/fsr/store/Overview'))
const CallHistory   = lazy(() => import('./views/fsr/store/CallHistory'))
const Reservations  = lazy(() => import('./views/fsr/store/Reservations'))
const Analytics     = lazy(() => import('./views/fsr/store/Analytics'))
const Settings      = lazy(() => import('./views/fsr/store/Settings'))
const CctvOverlay   = lazy(() => import('./views/fsr/store/CctvOverlay'))
const AiVoiceBot    = lazy(() => import('./views/fsr/store/AiVoiceBot'))

// Agency dashboard (에이전시 대시보드)
const AgencyLayout      = lazy(() => import('./views/agency/Layout'))
const AgencyOverview    = lazy(() => import('./views/agency/Overview'))
const AgencyStoreDetail = lazy(() => import('./views/agency/StoreDetail'))

// Admin (platform operator) — separate from Agency (관리자 — 에이전시와 분리)
const AdminLayout       = lazy(() => import('./views/admin/Layout'))
const AdminOverview     = lazy(() => import('./views/admin/Overview'))
const AdminAgencies     = lazy(() => import('./views/admin/Agencies'))
const AdminStores       = lazy(() => import('./views/admin/Stores'))
const AdminAuditLog     = lazy(() => import('./views/admin/AuditLog'))
const ArchitectureProof = lazy(() => import('./views/admin/ArchitectureProof'))
const OnboardingWizard  = lazy(() => import('./views/admin/onboarding/OnboardingWizard'))

// Stubs — "Coming Soon" placeholders until each page is built
const ComingSoon = ({ title }: { title: string }) => (
  <div style={{ padding: 32, color: '#64748b', fontSize: 18 }}>
    <strong>{title}</strong> — Coming Soon
  </div>
)

// Role-scoped guard — kicks user back to their home if role mismatches.
// (역할 가드 — 권한 불일치 시 home으로 리다이렉트)
function RequireRole({ allow, children }: { allow: UserRole[]; children: JSX.Element }) {
  const { token, role, email } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  if (!role || !allow.includes(role)) {
    return <Navigate to={homeRedirect(token, role, email)} replace />
  }
  return children
}

function homeRedirect(token: string | null, role: UserRole | null, _email: string | null) {
  if (!token) return '/login'
  if (role === 'ADMIN')  return '/admin/overview'
  if (role === 'AGENCY') return '/agency/overview'
  return '/fsr/store/overview'
}

function AppRoutes() {
  const { token, role, email } = useAuth()
  const home = homeRedirect(token, role, email)

  return (
    <Suspense fallback={<div style={{ padding: 32, color: '#64748b' }}>Loading...</div>}>
      <Routes>
        {/* Auth */}
        <Route path="/login" element={token ? <Navigate to={home} replace /> : <Login />} />

        {/* Agency routes (에이전시 라우트) */}
        <Route
          path="/agency"
          element={
            <RequireRole allow={['AGENCY']}>
              <AgencyLayout />
            </RequireRole>
          }
        >
          <Route index element={<Navigate to="overview" replace />} />
          <Route path="overview"         element={<AgencyOverview />} />
          <Route path="store/:storeId"   element={<AgencyStoreDetail />} />
        </Route>

        {/* Backward compat: old /agency/dashboard → /agency/overview */}
        <Route path="/agency/dashboard" element={<Navigate to="/agency/overview" replace />} />

        {/* Admin (platform operator) routes — separate from Agency */}
        <Route
          path="/admin"
          element={
            <RequireRole allow={['ADMIN']}>
              <AdminLayout />
            </RequireRole>
          }
        >
          <Route index element={<Navigate to="overview" replace />} />
          <Route path="overview"      element={<AdminOverview />} />
          <Route path="agencies"      element={<AdminAgencies />} />
          <Route path="stores"        element={<AdminStores />} />
          <Route path="users"         element={<ComingSoon title="Users & Roles" />} />
          <Route path="audit-log"     element={<AdminAuditLog />} />
          <Route path="system-health" element={<ComingSoon title="System Health" />} />
          <Route path="onboarding/new" element={<OnboardingWizard />} />
          <Route path="marketing/architecture-proof" element={<ArchitectureProof />} />
          {/* Backward compat: old /admin/architecture-proof */}
          <Route path="architecture-proof" element={<Navigate to="/admin/marketing/architecture-proof" replace />} />
        </Route>

        {/* FSR Store (store owner mode — store owner 모드) */}
        <Route
          path="/fsr/store"
          element={
            <RequireRole allow={['STORE']}>
              <StoreLayout />
            </RequireRole>
          }
        >
          <Route index element={<Navigate to="overview" replace />} />
          <Route path="overview"           element={<Overview />} />
          <Route path="ai-voice-bot"       element={<AiVoiceBot />} />
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
