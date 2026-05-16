// Auth context — login/logout state management (인증 컨텍스트 — 로그인/로그아웃 상태 관리)
import { createContext, useContext, useState, ReactNode } from 'react'
import api from './api'

// 3-tier role hierarchy: store owner / agency owner / platform admin
// (3단 권한 — 매장 오너 / 에이전시 오너 / 플랫폼 관리자)
export type UserRole = 'STORE' | 'AGENCY' | 'ADMIN'

// Decode the unsigned middle segment of a JWT to read claims.
// Verification already happened on the auth server — we only need to read role.
// (JWT 중간 segment를 base64url 디코드해서 claim 읽기 — 검증은 서버에서 끝남)
function decodeJwtPayload(token: string): { app_metadata?: { role?: string } } | null {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4)
    return JSON.parse(atob(padded))
  } catch {
    return null
  }
}

interface AuthState {
  token: string | null
  storeName: string | null
  storeId: string | null
  role: UserRole | null
  industry: string | null
  email: string | null
  isLoading: boolean
}

interface AuthContextValue extends AuthState {
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    token: localStorage.getItem('jm_token'),
    storeName: localStorage.getItem('jm_store_name'),
    storeId: localStorage.getItem('jm_store_id'),
    role: (localStorage.getItem('jm_role') as UserRole) ?? null,
    industry: localStorage.getItem('jm_industry'),
    email: localStorage.getItem('jm_email'),
    isLoading: false,
  })

  const login = async (email: string, password: string) => {
    setState((s) => ({ ...s, isLoading: true }))
    try {
      const { data } = await api.post('/auth/login', { email, password })

      // Resolve store info — agency users have no store (에이전시 유저는 스토어 없음)
      let storeName: string | null = null
      let storeId: string | null = null
      let role: UserRole = 'STORE'
      let industry: string | null = null

      // Platform admin via JWT app_metadata.role (Phase 2-E)
      // Seeded by backend/scripts/seed_admin_role.py, mutable via /admin/users.
      // (Phase 2-E — JWT app_metadata.role로 ADMIN 판별)
      const jwtRole = (decodeJwtPayload(data.access_token)?.app_metadata?.role ?? '').toLowerCase()
      if (jwtRole === 'admin') {
        role = 'ADMIN'
      } else {
        try {
          const storeResp = await api.get('/store/me', {
            headers: { Authorization: `Bearer ${data.access_token}` },
          })
          storeName = storeResp.data.name
          storeId = storeResp.data.id
          industry = storeResp.data.industry ?? null
          role = 'STORE'
        } catch (err: unknown) {
          const status = (err as { response?: { status?: number } }).response?.status
          if (status === 404) {
            // No store for this user — treat as agency account (스토어 없는 에이전시 계정)
            role = 'AGENCY'
          } else {
            throw err
          }
        }
      }

      // Persist only after full success (전체 성공 후에만 localStorage 저장)
      localStorage.setItem('jm_token', data.access_token)
      localStorage.setItem('jm_role', role)
      localStorage.setItem('jm_email', email)
      if (storeName) localStorage.setItem('jm_store_name', storeName)
      if (storeId) localStorage.setItem('jm_store_id', storeId)
      if (industry) localStorage.setItem('jm_industry', industry)

      setState({ token: data.access_token, storeName, storeId, role, industry, email, isLoading: false })
    } catch (err) {
      setState((s) => ({ ...s, isLoading: false }))
      throw err
    }
  }

  const logout = () => {
    localStorage.removeItem('jm_token')
    localStorage.removeItem('jm_store_name')
    localStorage.removeItem('jm_store_id')
    localStorage.removeItem('jm_role')
    localStorage.removeItem('jm_industry')
    localStorage.removeItem('jm_email')
    setState({ token: null, storeName: null, storeId: null, role: null, industry: null, email: null, isLoading: false })
  }

  return <AuthContext.Provider value={{ ...state, login, logout }}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
