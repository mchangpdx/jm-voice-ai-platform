// Agency Layout — sidebar with store list + outlet (에이전시 레이아웃 — 스토어 목록 사이드바 + 아웃렛)
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../../core/AuthContext'
import { getVerticalMeta } from '../../core/verticalLabels'
import api from '../../core/api'
import styles from './Layout.module.css'

interface StoreEntry {
  id: string
  name: string
  industry: string
}

export default function AgencyLayout() {
  const { logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [agencyName, setAgencyName] = useState<string>('JM Agency')
  const [stores, setStores] = useState<StoreEntry[]>([])
  const [sidebarOpen, setSidebarOpen] = useState(false)

  useEffect(() => {
    api.get('/agency/me').then((r) => setAgencyName(r.data.name)).catch(() => {})
    api.get('/agency/stores').then((r) => setStores(r.data)).catch(() => {})
  }, [])

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

      <aside className={`${styles.sidebar} ${sidebarOpen ? styles.sidebarVisible : ''}`}>
        {/* Brand (브랜드) */}
        <div className={styles.brand}>
          <div className={styles.brandLogo}>
            <svg viewBox="0 0 24 24" fill="white" width="18" height="18">
              <path d="M12 1a3 3 0 0 1 3 3v8a3 3 0 0 1-6 0V4a3 3 0 0 1 3-3z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" strokeWidth="2" stroke="white" fill="none" strokeLinecap="round" />
            </svg>
          </div>
          <span className={styles.brandName}>JM AI Voice</span>
        </div>

        {/* Agency name (에이전시 이름) */}
        <div className={styles.sectionLabel}>AGENCY</div>
        <div className={styles.agencyName}>{agencyName}</div>

        {/* Store navigation (스토어 네비게이션) */}
        <div className={styles.sectionLabel} style={{ marginTop: 12 }}>STORES</div>
        <nav className={styles.nav}>
          <NavLink
            to="/agency/overview"
            className={({ isActive }) =>
              `${styles.navItem} ${isActive ? styles.navItemActive : ''}`
            }
          >
            <span className={styles.navIcon}>⊞</span>
            All Stores
          </NavLink>
          {stores.map((s) => {
            const meta = getVerticalMeta(s.industry)
            return (
              <NavLink
                key={s.id}
                to={`/agency/store/${s.id}`}
                className={({ isActive }) =>
                  `${styles.navItem} ${isActive ? styles.navItemActive : ''}`
                }
              >
                <span className={styles.navIcon}>{meta.icon}</span>
                <span className={styles.storeNavName}>{s.name}</span>
              </NavLink>
            )
          })}
        </nav>

        {/* User section (사용자 섹션) */}
        <div className={styles.userSection}>
          <div className={styles.userAvatar}>A</div>
          <div className={styles.userInfo}>
            <div className={styles.userEmail}>{agencyName}</div>
            <div className={styles.userRole}>AGENCY</div>
          </div>
          <button className={styles.logoutBtn} onClick={handleLogout} title="Log Out">
            →
          </button>
        </div>
      </aside>

      <div className={styles.main}>
        <header className={styles.topBar}>
          <button className={styles.hamburger} onClick={() => setSidebarOpen(s => !s)} aria-label="Toggle menu">☰</button>
          <span className={styles.topBarBrand}>JM AI Voice Platform</span>
          <span className={styles.liveBadge}>● Live</span>
        </header>
        <div className={styles.content}>
          <Outlet />
        </div>
      </div>
    </div>
  )
}
