// Admin (platform operator) layout — global sidebar separate from Agency/Store.
// (관리자 레이아웃 — 에이전시/매장과 완전히 분리된 글로벌 사이드바)
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../../core/AuthContext'
import styles from './Layout.module.css'

export default function AdminLayout() {
  const { logout, email } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [sidebarOpen, setSidebarOpen] = useState(false)

  // Close sidebar on route change (모바일에서 라우트 변경 시 사이드바 닫기)
  useEffect(() => { setSidebarOpen(false) }, [location.pathname])

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const navItem = ({ isActive }: { isActive: boolean }) =>
    `${styles.navItem} ${isActive ? styles.navItemActive : ''}`

  return (
    <div className={styles.shell}>
      {sidebarOpen && <div className={styles.overlay} onClick={() => setSidebarOpen(false)} />}

      <aside className={`${styles.sidebar} ${sidebarOpen ? styles.sidebarVisible : ''}`}>
        {/* Brand */}
        <div className={styles.brand}>
          <div className={styles.brandLogo}>
            <svg viewBox="0 0 24 24" fill="white" width="18" height="18">
              <path d="M12 2L4 6v6c0 5 3.5 9.5 8 10 4.5-.5 8-5 8-10V6l-8-4z" />
            </svg>
          </div>
          <span className={styles.brandName}>JM Platform Admin</span>
        </div>

        <div className={styles.sectionLabel}>OPERATIONS</div>
        <nav className={styles.nav}>
          <NavLink to="/admin/overview" className={navItem}>
            <span className={styles.navIcon}>◎</span> Overview
          </NavLink>
          <NavLink to="/admin/agencies" className={navItem}>
            <span className={styles.navIcon}>⌂</span> Agencies
          </NavLink>
          <NavLink to="/admin/stores" className={navItem}>
            <span className={styles.navIcon}>⊞</span> Stores
          </NavLink>
          <NavLink to="/admin/users" className={navItem}>
            <span className={styles.navIcon}>◐</span> Users &amp; Roles
          </NavLink>
          <NavLink to="/admin/audit-log" className={navItem}>
            <span className={styles.navIcon}>§</span> Audit Log
          </NavLink>
          <NavLink to="/admin/system-health" className={navItem}>
            <span className={styles.navIcon}>♥</span> System Health
          </NavLink>
        </nav>

        <div className={styles.sectionLabel} style={{ marginTop: 12 }}>TOOLS</div>
        <nav className={styles.nav}>
          <NavLink to="/admin/onboarding/new" className={navItem}>
            <span className={styles.navIcon}>＋</span> New Store Onboarding
          </NavLink>
        </nav>

        <div className={styles.sectionLabel} style={{ marginTop: 12 }}>MARKETING</div>
        <nav className={styles.nav}>
          <NavLink to="/admin/marketing/architecture-proof" className={navItem}>
            <span className={styles.navIcon}>📐</span> Architecture Proof
          </NavLink>
        </nav>

        {/* User section */}
        <div className={styles.userSection}>
          <div className={styles.userAvatar}>A</div>
          <div className={styles.userInfo}>
            <div className={styles.userEmail}>{email ?? 'Admin'}</div>
            <div className={styles.userRole}>PLATFORM ADMIN</div>
          </div>
          <button className={styles.logoutBtn} onClick={handleLogout} title="Log Out">→</button>
        </div>
      </aside>

      <div className={styles.main}>
        <header className={styles.topBar}>
          <button className={styles.hamburger} onClick={() => setSidebarOpen(s => !s)} aria-label="Toggle menu">☰</button>
          <span className={styles.topBarBrand}>JM AI Voice Platform · Admin Console</span>
          <span className={styles.adminBadge}>● Admin</span>
        </header>
        <div className={styles.content}>
          <Outlet />
        </div>
      </div>
    </div>
  )
}
