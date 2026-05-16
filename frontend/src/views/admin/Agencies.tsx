// Admin Agencies Manager — list every agency with owner + store count.
// (관리자 에이전시 관리 — 모든 에이전시 + 오너 + 산하 매장수)
import { useEffect, useState } from 'react'
import api from '../../core/api'
import styles from './Agencies.module.css'

interface AgencyRow {
  id: string
  name: string
  owner_id: string
  owner_email: string
  store_count: number
  created_at: string | null
}

const fmtDate = (iso: string | null) => {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleDateString('en-US', {
      year: 'numeric', month: 'short', day: 'numeric',
    })
  } catch { return iso }
}

export default function AdminAgencies() {
  const [rows, setRows] = useState<AgencyRow[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('')
  const [busy, setBusy] = useState<string>('')
  const [toast, setToast] = useState<{ msg: string; err: boolean } | null>(null)

  const refresh = () =>
    api.get('/admin/agencies').then((r) => setRows(r.data)).catch(() => {})

  useEffect(() => {
    setLoading(true)
    refresh().finally(() => setLoading(false))
  }, [])

  const flash = (msg: string, err = false) => {
    setToast({ msg, err })
    setTimeout(() => setToast(null), 3000)
  }

  const handleRename = async (a: AgencyRow) => {
    const next = window.prompt(`Rename agency "${a.name}":`, a.name)?.trim()
    if (!next || next === a.name) return
    setBusy(a.id)
    try {
      await api.patch(`/admin/agencies/${a.id}`, { name: next })
      flash(`Renamed to "${next}"`)
      await refresh()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        .response?.data?.detail ?? 'Rename failed'
      flash(detail, true)
    } finally {
      setBusy('')
    }
  }

  const handleChangeOwner = async (a: AgencyRow) => {
    const next = window
      .prompt(`Reassign owner for "${a.name}" (email must already exist in Supabase Auth):`, a.owner_email)
      ?.trim()
      .toLowerCase()
    if (!next || next === a.owner_email.toLowerCase()) return
    setBusy(a.id)
    try {
      await api.patch(`/admin/agencies/${a.id}`, { owner_email: next })
      flash(`Owner changed to ${next}`)
      await refresh()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        .response?.data?.detail ?? 'Owner change failed'
      flash(detail, true)
    } finally {
      setBusy('')
    }
  }

  const handleDelete = async (a: AgencyRow) => {
    if (a.store_count > 0) {
      window.alert(
        `Cannot delete "${a.name}" — ${a.store_count} active stores remain.\nTransfer or disable them first.`,
      )
      return
    }
    if (!window.confirm(`Soft-delete agency "${a.name}"? This sets is_active=false.`)) return
    setBusy(a.id)
    try {
      await api.delete(`/admin/agencies/${a.id}`)
      flash(`Deleted "${a.name}"`)
      await refresh()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        .response?.data?.detail ?? 'Delete failed'
      flash(detail, true)
    } finally {
      setBusy('')
    }
  }

  const handleCreate = async () => {
    const name = window.prompt('New agency name:')?.trim()
    if (!name) return
    const email = window
      .prompt(`Owner email for "${name}" (must exist in Supabase Auth):`)
      ?.trim()
      .toLowerCase()
    if (!email) return
    setBusy('__create__')
    try {
      await api.post('/admin/agencies', { name, owner_email: email })
      flash(`Created "${name}"`)
      await refresh()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        .response?.data?.detail ?? 'Create failed'
      flash(detail, true)
    } finally {
      setBusy('')
    }
  }

  const f = filter.trim().toLowerCase()
  const visible = f
    ? rows.filter(
        (r) =>
          r.name.toLowerCase().includes(f) ||
          r.owner_email.toLowerCase().includes(f),
      )
    : rows

  return (
    <div className={styles.page}>
      {toast && (
        <div className={`${styles.toast} ${toast.err ? styles.toastErr : ''}`}>
          {toast.msg}
        </div>
      )}

      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Agencies</h1>
          <p className={styles.subtitle}>
            All customer organizations on the platform. Rename, reassign owner, or soft-delete.
          </p>
        </div>
        <div className={styles.headerActions}>
          <input
            className={styles.search}
            placeholder="Search by name or owner email…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <button
            className={styles.primaryBtn}
            onClick={handleCreate}
            disabled={busy === '__create__'}
          >
            + New Agency
          </button>
        </div>
      </div>

      {loading ? (
        <div className={styles.loading}>Loading…</div>
      ) : visible.length === 0 ? (
        <div className={styles.empty}>No agencies found.</div>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>AGENCY</th>
                <th>OWNER EMAIL</th>
                <th className={styles.numCol}>STORES</th>
                <th>CREATED</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {visible.map((a) => {
                const isBusy = busy === a.id
                return (
                  <tr key={a.id} className={isBusy ? styles.rowBusy : ''}>
                    <td className={styles.cellName}>{a.name}</td>
                    <td className={styles.cellEmail}>{a.owner_email || '—'}</td>
                    <td className={styles.numCol}>{a.store_count}</td>
                    <td className={styles.cellDate}>{fmtDate(a.created_at)}</td>
                    <td className={styles.actionCell}>
                      <button
                        className={styles.actionBtn}
                        disabled={isBusy}
                        onClick={() => handleRename(a)}
                      >
                        Rename
                      </button>
                      <button
                        className={styles.actionBtn}
                        disabled={isBusy}
                        onClick={() => handleChangeOwner(a)}
                      >
                        Owner
                      </button>
                      <button
                        className={`${styles.actionBtn} ${styles.actionDanger}`}
                        disabled={isBusy}
                        onClick={() => handleDelete(a)}
                      >
                        Delete
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
