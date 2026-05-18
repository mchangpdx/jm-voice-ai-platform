// FSR Store Layout — sidebar navigation matching legacy demo design
// (레거시 데모 디자인과 일치하는 사이드바 네비게이션 레이아웃)
import { useState, useEffect } from 'react'
import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../../../core/AuthContext'
import { VERTICAL_META } from '../../../core/verticalLabels'
import styles from './Layout.module.css'

// Return nav items based on industry — middle item label/icon varies by vertical
// (산업별로 중간 항목 레이블/아이콘이 다른 네비게이션 항목 반환)
function getNavItems(industry: string | null) {
  const industryItemMap: Record<string, { label: string; icon: string }> = {
    restaurant:    { label: 'Reservations',   icon: '📅' },
    home_services: { label: 'Jobs',           icon: '🔨' },
    beauty:        { label: 'Appointments',   icon: '💈' },
    auto_repair:   { label: 'Service Orders', icon: '🚗' },
  }
  const mid = industry ? (industryItemMap[industry] ?? industryItemMap.restaurant) : { label: 'Reservations', icon: '📅' }
  return [
    { to: 'overview',     label: 'Overview',    icon: '⊞' },
    { to: 'ai-voice-bot', label: 'AI Voice Bot', icon: '🤖' },
    { to: 'call-history', label: 'Call History', icon: '📞' },
    { to: 'reservations', label: mid.label,      icon: mid.icon },
    { to: 'analytics',    label: 'Analytics',    icon: '📈' },
    { to: 'settings',     label: 'Settings',     icon: '⚙' },
  ]
}

const SECURITY_ITEMS = [
  { to: 'security/solink',   label: 'POS Overlay Monitoring', icon: '🎥' },
  { to: 'security/theft',    label: 'Prevent Theft',          icon: '🛡' },
]

export default function StoreLayout() {
  const { storeName, industry, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const navItems = getNavItems(industry)
  const meta = industry ? VERTICAL_META[industry] : null

  // Close sidebar on route change (모바일에서 라우트 변경 시 사이드바 닫기)
  useEffect(() => { setSidebarOpen(false) }, [location.pathname])

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <div className={styles.shell}>
      {/* Mobile overlay (모바일 오버레이) */}
      {sidebarOpen && <div className={styles.overlay} onClick={() => setSidebarOpen(false)} />}

      {/* Left sidebar (좌측 사이드바) */}
      <aside className={`${styles.sidebar} ${sidebarOpen ? styles.sidebarVisible : ''}`}>
        {/* Brand header (브랜드 헤더) */}
        <div className={styles.brand}>
          <div className={styles.brandLogo}>
            <svg viewBox="0 0 24 24" fill="white" width="18" height="18">
              <path d="M12 1a3 3 0 0 1 3 3v8a3 3 0 0 1-6 0V4a3 3 0 0 1 3-3z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" strokeWidth="2" stroke="white" fill="none" strokeLinecap="round" />
            </svg>
          </div>
          <span className={styles.brandName}>JM AI Voice</span>
        </div>

        {/* Store section (스토어 섹션) */}
        <div className={styles.sectionLabel}>STORE</div>
        <div className={styles.storeName}>{storeName ?? '—'}</div>
        {/* Industry badge (산업 수직 배지) */}
        <div className={styles.industryBadge}>
          {meta?.icon} {meta?.industryLabel ?? 'Store'}
        </div>

        {/* Main nav (메인 네비게이션) */}
        <nav className={styles.nav}>
          {navItems.map(({ to, label, icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `${styles.navItem} ${isActive ? styles.navItemActive : ''}`
              }
            >
              <span className={styles.navIcon}>{icon}</span>
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Security section (보안 섹션) */}
        <div className={styles.sectionLabel} style={{ marginTop: 12 }}>SECURITY</div>
        <nav className={styles.nav}>
          {SECURITY_ITEMS.map(({ to, label, icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `${styles.navItem} ${isActive ? styles.navItemActive : ''}`
              }
            >
              <span className={styles.navIcon}>{icon}</span>
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Bottom user info (하단 사용자 정보) */}
        <div className={styles.userSection}>
          <div className={styles.userAvatar}>
            {storeName?.[0]?.toUpperCase() ?? 'S'}
          </div>
          <div className={styles.userInfo}>
            <div className={styles.userEmail}>{storeName ?? 'Store'}</div>
            <div className={styles.userRole}>STORE</div>
          </div>
          <button className={styles.logoutBtn} onClick={handleLogout} title="Log Out">
            →
          </button>
        </div>
      </aside>

      {/* Main content area (메인 콘텐츠 영역) */}
      <div className={styles.main}>
        {/* Top header bar (상단 헤더 바) */}
        <header className={styles.topBar}>
          <button className={styles.hamburger} onClick={() => setSidebarOpen(s => !s)} aria-label="Toggle menu">☰</button>
          <span className={styles.topBarBrand}>JM AI Voice Platform</span>
          <span className={styles.liveBadge}>● Live</span>
        </header>

        {/* Page content (페이지 콘텐츠) */}
        <div className={styles.content}>
          <Outlet />
        </div>
      </div>
    </div>
  )
}
