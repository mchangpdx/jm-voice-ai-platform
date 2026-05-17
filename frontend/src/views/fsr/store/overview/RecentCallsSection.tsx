// Recent Calls — last 5 voice agent calls + link to full history.
// (최근 5 통화 + Call History 전체 링크)
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../../../../core/api'
import styles from '../Overview.module.css'

interface CallLogItem {
  call_id:        string
  start_time:     string
  customer_phone: string | null
  duration:       number
  sentiment:      string | null
  call_status:    string
  cost:           number
  recording_url:  string | null
  summary:        string | null
  is_store_busy:  boolean
}

const maskPhone = (phone: string | null): string => {
  if (!phone) return '—'
  const digits = phone.replace(/\D/g, '')
  if (digits.length < 4) return phone
  return `••• ${digits.slice(-4)}`
}

const fmtDuration = (sec: number): string => {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

const fmtCallTime = (iso: string): string => {
  try {
    return new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  } catch { return iso }
}

export default function RecentCallsSection() {
  const [recentCalls, setRecentCalls] = useState<CallLogItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api
      .get('/store/call-logs?limit=5')
      .then((r) => setRecentCalls(r.data?.items ?? []))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className={styles.recentCallsPanel}>
      <div className={styles.panelHeader}>
        <span className={styles.panelIcon}>📞</span>
        <div>
          <div className={styles.panelTitle}>Recent Calls</div>
          <div className={styles.panelDesc}>Latest 5 voice agent calls — tap row to see full transcript</div>
        </div>
        <Link to="/fsr/store/call-history" className={styles.viewAllLink}>View all →</Link>
      </div>

      {loading ? (
        <div className={styles.loading}>Loading recent calls…</div>
      ) : recentCalls.length === 0 ? (
        <div className={styles.empty}>No calls yet</div>
      ) : (
        <table className={styles.recentTable}>
          <thead>
            <tr>
              <th>TIME</th>
              <th>PHONE</th>
              <th>DURATION</th>
              <th>STATUS</th>
              <th>SUMMARY</th>
            </tr>
          </thead>
          <tbody>
            {recentCalls.map((c) => (
              <tr key={c.call_id}>
                <td>{fmtCallTime(c.start_time)}</td>
                <td>{maskPhone(c.customer_phone)}</td>
                <td>{fmtDuration(c.duration)}</td>
                <td>
                  <span className={styles.callStatus}>{c.call_status}</span>
                </td>
                <td className={styles.summaryCell} title={c.summary ?? ''}>
                  {c.summary ?? '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
