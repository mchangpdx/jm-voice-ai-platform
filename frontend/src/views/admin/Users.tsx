// Admin Users & Roles Manager — list Supabase users, change role, disable.
// (관리자 사용자/역할 관리 — Supabase 사용자 + 역할 변경 + 비활성화)
import { useEffect, useMemo, useState } from 'react'
import api from '../../core/api'
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

  const handleChangeRole = async (u: UserRow) => {
    const choice = window
      .prompt(
        `Change role for ${u.email ?? u.id}.\nCurrent: ${u.role}\nEnter STORE, AGENCY, or ADMIN:`,
        u.role,
      )
      ?.trim()
      .toUpperCase()
    if (!choice || choice === u.role) return
    if (!ROLE_OPTIONS.includes(choice as Role)) {
      flash(`Invalid role "${choice}"`, true)
      return
    }
    setBusy(u.id)
    try {
      await api.patch(`/admin/users/${u.id}/role`, { role: choice })
      flash(`Role updated to ${choice}`)
      await refresh()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        .response?.data?.detail ?? 'Role change failed'
      flash(detail, true)
    } finally {
      setBusy('')
    }
  }

  const handleDisable = async (u: UserRow) => {
    const owned = u.owned_agencies.length + u.owned_stores.length
    if (owned > 0) {
      window.alert(
        `Cannot disable ${u.email ?? u.id} — still owns ${u.owned_agencies.length} agencies and ${u.owned_stores.length} stores.\nTransfer them first.`,
      )
      return
    }
    if (!window.confirm(`Disable ${u.email ?? u.id}? They will be blocked from logging in.`)) return
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
        <div className={styles.loading}>Loading…</div>
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
                const ownedSummary =
                  u.owned_agencies.length === 0 && u.owned_stores.length === 0
                    ? '—'
                    : [
                        u.owned_agencies.length ? `${u.owned_agencies.length} agency` : null,
                        u.owned_stores.length   ? `${u.owned_stores.length} store`   : null,
                      ].filter(Boolean).join(' · ')
                return (
                  <tr key={u.id} className={isBusy ? styles.rowBusy : ''}>
                    <td className={styles.cellEmail}>
                      {u.email ?? '—'}
                      {u.is_disabled && <span className={styles.disabledBadge}>DISABLED</span>}
                    </td>
                    <td>
                      <span className={`${styles.roleBadge} ${styles[`role${u.role}`]}`}>
                        {u.role}
                      </span>
                    </td>
                    <td className={styles.cellOwned}>{ownedSummary}</td>
                    <td className={styles.cellDate}>{fmtRelative(u.last_sign_in_at)}</td>
                    <td className={styles.cellDate}>{fmtDate(u.created_at)}</td>
                    <td className={styles.actionCell}>
                      <button
                        className={styles.actionBtn}
                        disabled={isBusy}
                        onClick={() => handleChangeRole(u)}
                      >
                        Role
                      </button>
                      <button
                        className={`${styles.actionBtn} ${styles.actionDanger}`}
                        disabled={isBusy || u.is_disabled}
                        onClick={() => handleDisable(u)}
                      >
                        Disable
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
