// Admin Stores Manager — every store across every agency, with view toggle.
// (관리자 매장 관리 — 모든 에이전시 산하 전 매장, 뷰 토글 포함)
import { useEffect, useMemo, useState } from 'react'
import api from '../../core/api'
import { getVerticalMeta } from '../../core/verticalLabels'
import StoreViewToggle, {
  StoreViewMode,
  loadStoreView,
  saveStoreView,
} from '../../components/store-view/StoreViewToggle'
import styles from './Stores.module.css'

interface StoreRow {
  id: string
  name: string
  industry: string
  agency_id: string
  agency_name: string
  phone: string | null
  pos_provider: string | null
  is_active: boolean
  created_at: string | null
}

const VIEW_STORAGE_KEY = 'jm_admin_store_view'

const fmtDate = (iso: string | null) => {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleDateString('en-US', {
      year: 'numeric', month: 'short', day: 'numeric',
    })
  } catch { return iso }
}

const fmtPhone = (phone: string | null) => {
  if (!phone) return '—'
  return phone
}

interface AgencyOption { id: string; name: string }

export default function AdminStores() {
  const [rows, setRows] = useState<StoreRow[]>([])
  const [agencies, setAgencies] = useState<AgencyOption[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('')
  const [vertical, setVertical] = useState<string>('all')
  const [view, setView] = useState<StoreViewMode>(() => loadStoreView(VIEW_STORAGE_KEY))
  const [busy, setBusy] = useState<string>('')
  const [toast, setToast] = useState<{ msg: string; err: boolean } | null>(null)

  const onViewChange = (next: StoreViewMode) => {
    setView(next)
    saveStoreView(VIEW_STORAGE_KEY, next)
  }

  const refresh = () =>
    api.get('/admin/stores').then((r) => setRows(r.data)).catch(() => {})

  useEffect(() => {
    setLoading(true)
    Promise.all([
      refresh(),
      api.get('/admin/agencies')
        .then((r) =>
          setAgencies(r.data.map((a: { id: string; name: string }) => ({ id: a.id, name: a.name }))),
        )
        .catch(() => {}),
    ]).finally(() => setLoading(false))
  }, [])

  const flash = (msg: string, err = false) => {
    setToast({ msg, err })
    setTimeout(() => setToast(null), 3000)
  }

  const errDetail = (e: unknown) =>
    (e as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? 'Request failed'

  const handleRename = async (s: StoreRow) => {
    const next = window.prompt(`Rename store "${s.name}":`, s.name)?.trim()
    if (!next || next === s.name) return
    setBusy(s.id)
    try {
      await api.patch(`/admin/stores/${s.id}`, { name: next })
      flash(`Renamed to "${next}"`)
      await refresh()
    } catch (e) {
      flash(errDetail(e), true)
    } finally {
      setBusy('')
    }
  }

  const handleToggleActive = async (s: StoreRow) => {
    const action = s.is_active ? 'disable' : 'enable'
    if (!window.confirm(`${action[0].toUpperCase()}${action.slice(1)} store "${s.name}"?`)) return
    setBusy(s.id)
    try {
      await api.patch(`/admin/stores/${s.id}`, { is_active: !s.is_active })
      flash(`Store ${action}d`)
      await refresh()
    } catch (e) {
      flash(errDetail(e), true)
    } finally {
      setBusy('')
    }
  }

  const handleTransfer = async (s: StoreRow) => {
    const options = agencies
      .filter((a) => a.id !== s.agency_id)
      .map((a, i) => `${i + 1}. ${a.name} (${a.id.slice(0, 8)}…)`)
      .join('\n')
    if (!options) {
      window.alert('No other agencies available as transfer target.')
      return
    }
    const pick = window.prompt(
      `Transfer "${s.name}" → which agency?\n\n${options}\n\nEnter number:`,
    )
    if (!pick) return
    const idx = parseInt(pick.trim(), 10) - 1
    const candidates = agencies.filter((a) => a.id !== s.agency_id)
    const target = candidates[idx]
    if (!target) {
      window.alert('Invalid selection.')
      return
    }
    if (!window.confirm(`Move "${s.name}" to "${target.name}"?`)) return
    setBusy(s.id)
    try {
      await api.post(`/admin/stores/${s.id}/transfer`, { new_agency_id: target.id })
      flash(`Transferred to "${target.name}"`)
      await refresh()
    } catch (e) {
      flash(errDetail(e), true)
    } finally {
      setBusy('')
    }
  }

  const handleDelete = async (s: StoreRow) => {
    if (!window.confirm(`Soft-delete store "${s.name}"? (Sets is_active=false)`)) return
    setBusy(s.id)
    try {
      await api.delete(`/admin/stores/${s.id}`)
      flash(`Deleted "${s.name}"`)
      await refresh()
    } catch (e) {
      flash(errDetail(e), true)
    } finally {
      setBusy('')
    }
  }

  const verticals = useMemo(() => {
    const set = new Set(rows.map((r) => r.industry))
    return ['all', ...Array.from(set).sort()]
  }, [rows])

  const visible = useMemo(() => {
    const f = filter.trim().toLowerCase()
    return rows.filter((r) => {
      if (vertical !== 'all' && r.industry !== vertical) return false
      if (!f) return true
      return (
        r.name.toLowerCase().includes(f) ||
        r.agency_name.toLowerCase().includes(f) ||
        (r.phone ?? '').toLowerCase().includes(f)
      )
    })
  }, [rows, filter, vertical])

  return (
    <div className={styles.page}>
      {toast && (
        <div className={`${styles.toast} ${toast.err ? styles.toastErr : ''}`}>
          {toast.msg}
        </div>
      )}
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Stores</h1>
          <p className={styles.subtitle}>
            All stores across all agencies. Use filters to narrow down by vertical.
          </p>
        </div>
        <StoreViewToggle value={view} onChange={onViewChange} />
      </div>

      <div className={styles.filtersRow}>
        <input
          className={styles.search}
          placeholder="Search by store, agency, phone…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <div className={styles.verticalChips}>
          {verticals.map((v) => {
            const label = v === 'all' ? 'All' : getVerticalMeta(v).industryLabel
            const icon = v === 'all' ? '⊞' : getVerticalMeta(v).icon
            return (
              <button
                key={v}
                className={`${styles.chip} ${vertical === v ? styles.chipActive : ''}`}
                onClick={() => setVertical(v)}
              >
                <span className={styles.chipIcon}>{icon}</span> {label}
              </button>
            )
          })}
        </div>
        <span className={styles.countTag}>{visible.length} / {rows.length}</span>
      </div>

      {loading ? (
        <div className={styles.empty}>Loading…</div>
      ) : visible.length === 0 ? (
        <div className={styles.empty}>No stores match these filters.</div>
      ) : view === 'cards' ? (
        <div className={styles.cardGrid}>
          {visible.map((s) => {
            const meta = getVerticalMeta(s.industry)
            return (
              <div key={s.id} className={styles.card}>
                <div className={styles.cardTop}>
                  <span className={styles.cardIcon}>{meta.icon}</span>
                  <div className={styles.cardHead}>
                    <div className={styles.cardName}>{s.name}</div>
                    <div className={styles.cardMeta}>{meta.industryLabel}</div>
                  </div>
                  <span className={`${styles.statusDot} ${s.is_active ? styles.dotOn : styles.dotOff}`} />
                </div>
                <div className={styles.cardKv}>
                  <span className={styles.kvLabel}>Agency</span>
                  <span className={styles.kvValue}>{s.agency_name || '—'}</span>
                </div>
                <div className={styles.cardKv}>
                  <span className={styles.kvLabel}>Phone</span>
                  <span className={styles.kvValue}>{fmtPhone(s.phone)}</span>
                </div>
                <div className={styles.cardKv}>
                  <span className={styles.kvLabel}>POS</span>
                  <span className={styles.kvValue}>{s.pos_provider ?? '—'}</span>
                </div>
                <div className={styles.cardKv}>
                  <span className={styles.kvLabel}>Created</span>
                  <span className={styles.kvValue}>{fmtDate(s.created_at)}</span>
                </div>
                <div className={styles.cardActions}>
                  <button
                    className={styles.cardBtn}
                    onClick={() => handleRename(s)}
                    disabled={busy === s.id}
                  >Rename</button>
                  <button
                    className={styles.cardBtn}
                    onClick={() => handleToggleActive(s)}
                    disabled={busy === s.id}
                  >{s.is_active ? 'Disable' : 'Enable'}</button>
                  <button
                    className={styles.cardBtn}
                    onClick={() => handleTransfer(s)}
                    disabled={busy === s.id}
                  >Transfer</button>
                  <button
                    className={`${styles.cardBtn} ${styles.cardBtnDanger}`}
                    onClick={() => handleDelete(s)}
                    disabled={busy === s.id}
                  >Delete</button>
                </div>
              </div>
            )
          })}
        </div>
      ) : view === 'list' ? (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>STORE</th>
                <th>AGENCY</th>
                <th>VERTICAL</th>
                <th>PHONE</th>
                <th>POS</th>
                <th>STATUS</th>
                <th>CREATED</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {visible.map((s) => {
                const meta = getVerticalMeta(s.industry)
                return (
                  <tr key={s.id}>
                    <td>
                      <span className={styles.tableIcon}>{meta.icon}</span>
                      <span className={styles.tableName}>{s.name}</span>
                    </td>
                    <td className={styles.cellMuted}>{s.agency_name || '—'}</td>
                    <td className={styles.cellMuted}>{meta.industryLabel}</td>
                    <td className={styles.cellMono}>{fmtPhone(s.phone)}</td>
                    <td className={styles.cellMuted}>{s.pos_provider ?? '—'}</td>
                    <td>
                      <span className={s.is_active ? styles.badgeOn : styles.badgeOff}>
                        {s.is_active ? 'Active' : 'Disabled'}
                      </span>
                    </td>
                    <td className={styles.cellMuted}>{fmtDate(s.created_at)}</td>
                    <td className={styles.rowActions}>
                      <button
                        className={styles.rowBtn}
                        onClick={() => handleRename(s)}
                        disabled={busy === s.id}
                      >Rename</button>
                      <button
                        className={styles.rowBtn}
                        onClick={() => handleToggleActive(s)}
                        disabled={busy === s.id}
                      >{s.is_active ? 'Disable' : 'Enable'}</button>
                      <button
                        className={styles.rowBtn}
                        onClick={() => handleTransfer(s)}
                        disabled={busy === s.id}
                      >Move</button>
                      <button
                        className={`${styles.rowBtn} ${styles.rowBtnDanger}`}
                        onClick={() => handleDelete(s)}
                        disabled={busy === s.id}
                      >Del</button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className={styles.compactList}>
          {visible.map((s) => {
            const meta = getVerticalMeta(s.industry)
            return (
              <div key={s.id} className={styles.compactRow}>
                <span className={`${styles.statusDot} ${s.is_active ? styles.dotOn : styles.dotOff}`} />
                <span className={styles.compactIcon}>{meta.icon}</span>
                <span className={styles.compactName}>{s.name}</span>
                <span className={styles.compactAgency}>{s.agency_name}</span>
                <span className={styles.compactPos}>{s.pos_provider ?? '—'}</span>
                <span className={styles.compactPhone}>{fmtPhone(s.phone)}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
