// Admin Users & Roles Manager — list Supabase users, change role, disable.
// (관리자 사용자/역할 관리 — Supabase 사용자 + 역할 변경 + 비활성화)
import { useEffect, useMemo, useState } from 'react'
import api from '../../core/api'
import { SkeletonRow } from '../../components/Skeleton/Skeleton'
import styles from './Users.module.css'

type Role = 'STORE' | 'AGENCY' | 'ADMIN'

interface OwnedRef {
  id: string
  name: string
  is_active: boolean
}

interface UserRow {
  id: string
  email: string | null
  role: Role
  last_sign_in_at: string | null
  created_at: string | null
  is_disabled: boolean
  owned_agencies: OwnedRef[]
  owned_stores:   OwnedRef[]
}

const ROLE_OPTIONS: Role[] = ['STORE', 'AGENCY', 'ADMIN']

const fmtDate = (iso: string | null) => {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleDateString('en-US', {
      year: 'numeric', month: 'short', day: 'numeric',
    })
  } catch { return iso }
}

const fmtRelative = (iso: string | null) => {
  if (!iso) return 'Never'
  const ts = new Date(iso).getTime()
  if (!Number.isFinite(ts)) return iso
  const diffMin = (Date.now() - ts) / 60000
  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${Math.floor(diffMin)} min ago`
  if (diffMin < 60 * 24) return `${Math.floor(diffMin / 60)} h ago`
  if (diffMin < 60 * 24 * 30) return `${Math.floor(diffMin / (60 * 24))} d ago`
  return fmtDate(iso)
}

export default function AdminUsers() {
  const [rows, setRows] = useState<UserRow[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('')
  const [roleFilter, setRoleFilter] = useState<'ALL' | Role>('ALL')
  const [busy, setBusy] = useState<string>('')
  const [confirmingDisable, setConfirmingDisable] = useState<string>('')   // user_id awaiting 2nd click
  const [toast, setToast] = useState<{ msg: string; err: boolean } | null>(null)

  const refresh = () =>
    api.get('/admin/users', { params: { limit: 500 } })
      .then((r) => setRows(r.data.items ?? []))
      .catch(() => {})

  useEffect(() => {
    setLoading(true)
    refresh().finally(() => setLoading(false))
  }, [])

  const flash = (msg: string, err = false) => {
    setToast({ msg, err })
    setTimeout(() => setToast(null), 3000)
  }

  // Inline role change — fired by the row's <select> onChange.
  // Backend's last-admin-demotion guard returns 409; we surface it via toast.
  // (인라인 select 변경 — backend의 마지막 admin 강등 차단을 토스트로 노출)
  const handleChangeRole = async (u: UserRow, next: Role) => {
    if (next === u.role) return
    setBusy(u.id)
    try {
      await api.patch(`/admin/users/${u.id}/role`, { role: next })
      flash(`Role updated to ${next}`)
      await refresh()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        .response?.data?.detail ?? 'Role change failed'
      flash(detail, true)
    } finally {
      setBusy('')
    }
  }

  // Two-stage disable — first click arms confirm state, second click within 4s
  // commits. Owned-resource rows are pre-disabled with a tooltip; no need to
  // post-hoc alert. (2단계 확인 — 첫 클릭 arm, 두 번째 클릭 commit)
  const handleDisableClick = (u: UserRow) => {
    if (confirmingDisable === u.id) {
      void actuallyDisable(u)
      setConfirmingDisable('')
      return
    }
    setConfirmingDisable(u.id)
    setTimeout(() => {
      setConfirmingDisable((prev) => (prev === u.id ? '' : prev))
    }, 4000)
  }

  const actuallyDisable = async (u: UserRow) => {
    setBusy(u.id)
    try {
      await api.delete(`/admin/users/${u.id}`)
      flash(`Disabled ${u.email ?? u.id}`)
      await refresh()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        .response?.data?.detail ?? 'Disable failed'
      flash(detail, true)
    } finally {
      setBusy('')
    }
  }

  const visible = useMemo(() => {
    const f = filter.trim().toLowerCase()
    return rows.filter((u) => {
      if (roleFilter !== 'ALL' && u.role !== roleFilter) return false
      if (!f) return true
      return (u.email ?? '').toLowerCase().includes(f) || u.id.toLowerCase().includes(f)
    })
  }, [rows, filter, roleFilter])

  return (
    <div className={styles.page}>
      {toast && (
        <div className={`${styles.toast} ${toast.err ? styles.toastErr : ''}`}>
          {toast.msg}
        </div>
      )}

      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Users &amp; Roles</h1>
          <p className={styles.subtitle}>
            All Supabase auth users. Role drives access (STORE / AGENCY / ADMIN). Disabling
            requires ownership transfer first.
          </p>
        </div>
        <div className={styles.headerActions}>
          <select
            className={styles.roleSelect}
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value as 'ALL' | Role)}
          >
            <option value="ALL">All roles</option>
            {ROLE_OPTIONS.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
          <input
            className={styles.search}
            placeholder="Search by email or user_id…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
      </div>

      {loading ? (
        <div className={styles.tableWrap}>
          {Array.from({ length: 6 }).map((_, i) => <SkeletonRow key={i} cells={5} />)}
        </div>
      ) : visible.length === 0 ? (
        <div className={styles.empty}>No users match the current filter.</div>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>EMAIL</th>
                <th>ROLE</th>
                <th>OWNED</th>
                <th>LAST SIGN-IN</th>
                <th>CREATED</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {visible.map((u) => {
                const isBusy = busy === u.id
                const ownedCount = u.owned_agencies.length + u.owned_stores.length
                const ownedSummary =
                  ownedCount === 0
                    ? '—'
                    : [
                        u.owned_agencies.length ? `${u.owned_agencies.length} agency` : null,
                        u.owned_stores.length   ? `${u.owned_stores.length} store`   : null,
                      ].filter(Boolean).join(' · ')
                const isConfirmingDisable = confirmingDisable === u.id
                const disableLocked = isBusy || u.is_disabled || ownedCount > 0
                const disableTooltip = u.is_disabled
                  ? 'User is already disabled'
                  : ownedCount > 0
                    ? `Transfer ${u.owned_agencies.length} agency / ${u.owned_stores.length} store first`
                    : isConfirmingDisable
                      ? 'Click again within 4s to confirm'
                      : 'Disable user — they will be blocked from logging in'
                return (
                  <tr key={u.id} className={isBusy ? styles.rowBusy : ''}>
                    <td className={styles.cellEmail}>
                      {u.email ?? '—'}
                      {u.is_disabled && <span className={styles.disabledBadge}>DISABLED</span>}
                    </td>
                    <td>
                      <select
                        className={`${styles.roleSelectInline} ${styles[`role${u.role}`]}`}
                        value={u.role}
                        disabled={isBusy || u.is_disabled}
                        onChange={(e) => handleChangeRole(u, e.target.value as Role)}
                        aria-label={`Change role for ${u.email ?? u.id}`}
                      >
                        {ROLE_OPTIONS.map((r) => (
                          <option key={r} value={r}>{r}</option>
                        ))}
                      </select>
                    </td>
                    <td className={styles.cellOwned}>{ownedSummary}</td>
                    <td className={styles.cellDate}>{fmtRelative(u.last_sign_in_at)}</td>
                    <td className={styles.cellDate}>{fmtDate(u.created_at)}</td>
                    <td className={styles.actionCell}>
                      <button
                        className={`${styles.actionBtn} ${styles.actionDanger} ${isConfirmingDisable ? styles.actionConfirm : ''}`}
                        disabled={disableLocked}
                        onClick={() => handleDisableClick(u)}
                        title={disableTooltip}
                      >
                        {isConfirmingDisable ? 'Click to confirm' : 'Disable'}
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
