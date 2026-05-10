// Login page — matches legacy aidemo.jmtechone.com/login design (레거시 로그인 페이지 디자인 일치)
import { useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../core/AuthContext'
import styles from './Login.module.css'

// Admin alias — typing 'admin' as the identifier resolves to the Supabase
// admin@test.com account (AGENCY role) and lands the user on the investor
// /admin/architecture-proof page instead of /agency/overview.
// (admin 별칭 — 아이디 'admin' 입력 시 admin@test.com 계정으로 로그인 후
// /admin/architecture-proof로 직행)
const ADMIN_ALIAS = 'admin'
const ADMIN_EMAIL = 'admin@test.com'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const normalized = email.trim().toLowerCase()
      const isAdmin    = normalized === ADMIN_ALIAS
      const loginEmail = isAdmin ? ADMIN_EMAIL : email
      await login(loginEmail, password)
      navigate(isAdmin ? '/admin/architecture-proof' : '/')
    } catch {
      setError('Invalid email or password')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        {/* Logo (로고) */}
        <div className={styles.logoWrap}>
          <div className={styles.logo}>
            <svg viewBox="0 0 24 24" fill="white" width="28" height="28">
              <path d="M12 1a3 3 0 0 1 3 3v8a3 3 0 0 1-6 0V4a3 3 0 0 1 3-3z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" strokeWidth="2" stroke="white" fill="none" strokeLinecap="round" />
              <line x1="12" y1="19" x2="12" y2="23" stroke="white" strokeWidth="2" strokeLinecap="round" />
              <line x1="8" y1="23" x2="16" y2="23" stroke="white" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </div>
        </div>

        <h1 className={styles.title}>JM AI Voice Platform</h1>
        <p className={styles.subtitle}>Sign in to your account</p>

        <form onSubmit={handleSubmit} className={styles.form}>
          <div className={styles.field}>
            <label className={styles.label}>Email</label>
            <input
              type="text"
              className={styles.input}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com or admin"
              required
              autoFocus
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
            />
          </div>

          <div className={styles.field}>
            <label className={styles.label}>Password</label>
            <input
              type="password"
              className={styles.input}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              required
            />
          </div>

          {error && <p className={styles.error}>{error}</p>}

          <button type="submit" className={styles.btn} disabled={loading}>
            {loading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>

        <p className={styles.footer}>
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
          Multi-store access is available after login.
        </p>
      </div>
    </div>
  )
}
