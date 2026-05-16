// Store Overview — Harness-methodology Business KPIs (Harness 방법론 비즈니스 KPI 대시보드)
// MCRR | LCS | LCR | UV | Monthly Impact + AI Persona + Live Orders
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../../core/AuthContext'
import api from '../../../core/api'
import Tier3AlertBadge from '../../../components/Tier3AlertBadge'
import { getVerticalMeta } from '../../../core/verticalLabels'
import styles from './Overview.module.css'

type Period = 'today' | 'week' | 'month' | 'all'

interface Metrics {
  mcrr: number
  lcs: number
  lcr: number
  upselling_value: number
  monthly_impact: number
  total_calls: number
  successful_calls: number
  total_ai_revenue: number
  avg_ticket: number
  success_rate: number
  using_real_busy_data: boolean
}

interface Order {
  id: number
  customer_phone: string | null
  customer_email: string | null
  total_amount: number
  status: string
  created_at: string
  items: Array<{ name?: string; quantity?: number }>
}

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

const PERIODS: { key: Period; label: string }[] = [
  { key: 'today', label: 'Today' },
  { key: 'week',  label: 'Week'  },
  { key: 'month', label: 'Month' },
  { key: 'all',   label: 'All'   },
]

// Cross-component sync event for voice-bot prompt fields.
// Fired by Overview + AiVoiceBot after a successful save so the
// other view re-syncs without a full reload.
// (Overview + AiVoiceBot 간 daily instructions 동기화 이벤트)
const VOICE_BOT_EVENT = 'voice-bot:updated'

interface VoiceBotPayload {
  temporary_prompt: string | null
  system_prompt?: string | null
}

export default function Overview() {
  const { storeName, industry } = useAuth()
  // Vertical-aware KPI labels — falls back to restaurant if industry is null/unknown
  // (산업별 KPI 라벨 — null/미지의 industry는 restaurant 기본값으로 폴백)
  const meta = getVerticalMeta(industry ?? 'restaurant')
  const [period, setPeriod] = useState<Period>('all')
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [orders, setOrders] = useState<Order[]>([])
  const [dailyInstructions, setDailyInstructions] = useState('')
  const [savedInstructions, setSavedInstructions] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [loadingMetrics, setLoadingMetrics] = useState(true)
  const [loadingOrders, setLoadingOrders] = useState(true)
  const [recentCalls, setRecentCalls] = useState<CallLogItem[]>([])
  const [loadingCalls, setLoadingCalls] = useState(true)

  useEffect(() => {
    if (!period) return
    setLoadingMetrics(true)
    api.get(`/store/metrics?period=${period}`)
      .then((r) => setMetrics(r.data))
      .finally(() => setLoadingMetrics(false))
  }, [period])

  useEffect(() => {
    setLoadingOrders(true)
    api.get('/store/orders?limit=10')
      .then((r) => setOrders(r.data))
      .finally(() => setLoadingOrders(false))
  }, [])

  useEffect(() => {
    api.get('/store/call-logs?limit=5')
      .then((r) => setRecentCalls(r.data?.items ?? []))
      .finally(() => setLoadingCalls(false))
  }, [])

  // Voice-bot Daily Instructions — single source of truth = backend /store/voice-bot.
  // (Daily Instructions 단일 진실원천 = /store/voice-bot temporary_prompt)
  useEffect(() => {
    api.get('/store/voice-bot')
      .then((r) => {
        const value = (r.data?.temporary_prompt ?? '') as string
        setDailyInstructions(value)
        setSavedInstructions(value)
      })
      .catch(() => {})
  }, [])

  // Cross-component sync: AiVoiceBot saves → Overview reflects without reload.
  // (AiVoiceBot에서 저장 시 Overview도 즉시 반영)
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<VoiceBotPayload>).detail
      if (!detail) return
      const value = detail.temporary_prompt ?? ''
      setDailyInstructions(value)
      setSavedInstructions(value)
    }
    window.addEventListener(VOICE_BOT_EVENT, handler)
    return () => window.removeEventListener(VOICE_BOT_EVENT, handler)
  }, [])

  const handleSave = async () => {
    if (saving) return
    if (dailyInstructions === savedInstructions) return
    setSaving(true)
    setSaveError('')
    try {
      const r = await api.patch('/store/voice-bot', {
        temporary_prompt: dailyInstructions,
      })
      const updated = (r.data?.temporary_prompt ?? '') as string
      setSavedInstructions(updated)
      setDailyInstructions(updated)
      window.dispatchEvent(
        new CustomEvent<VoiceBotPayload>(VOICE_BOT_EVENT, {
          detail: { temporary_prompt: updated },
        }),
      )
    } catch {
      setSaveError('Save failed. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  const fmt = (n: number) => `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  const fmtDate = (iso: string) => {
    try { return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }
    catch { return iso }
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
    try { return new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }) }
    catch { return iso }
  }

  const m = metrics
  const pendingCount = orders.filter((o) => o.status === 'fired_unpaid').length

  return (
    <div className={styles.page}>
      {/* Header (헤더) */}
      <div className={styles.pageHeader}>
        <div>
          <h1 className={styles.storeName}>{storeName ?? 'Store'}</h1>
          <p className={styles.pageDesc}>AI ROI analytics, persona control, and live call orders — all in one place.</p>
        </div>
        {/* TODO: wire up GET /api/store/alerts/tier3 (backend pending) */}
        <Tier3AlertBadge count={0} />
      </div>

      {/* Period filter (기간 필터) */}
      <div className={styles.periodRow}>
        <span className={styles.periodLabel}>Period:</span>
        {PERIODS.map(({ key, label }) => (
          <button
            key={key}
            className={`${styles.periodBtn} ${period === key ? styles.periodBtnActive : ''}`}
            onClick={() => setPeriod(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ── Row 1: Primary Business KPIs (1행: 핵심 비즈니스 KPI) ── */}
      <div className={styles.kpiRow}>
        {/* MCRR — Primary revenue (vertical-aware label) */}
        <div className={`${styles.kpiCard} ${styles.kpiGreen}`}>
          <div className={styles.kpiTop}>
            <span className={styles.kpiLabel}>{meta.primaryRevenueLabel}</span>
            <span className={styles.kpiBadge}>MCRR</span>
          </div>
          <div className={styles.kpiValue}>{loadingMetrics ? '—' : fmt(m?.mcrr ?? 0)}</div>
          <div className={styles.kpiSub}>
            {m?.using_real_busy_data
              ? 'Busy-hour calls answered by AI × success rate × avg ticket'
              : 'Est. missed calls × AI success rate × avg ticket'}
          </div>
        </div>

        {/* LCS — Labor Cost Savings */}
        <div className={`${styles.kpiCard} ${styles.kpiBlue}`}>
          <div className={styles.kpiTop}>
            <span className={styles.kpiLabel}>Labor Cost Savings</span>
            <span className={styles.kpiBadge}>LCS</span>
          </div>
          <div className={styles.kpiValue}>{loadingMetrics ? '—' : fmt(m?.lcs ?? 0)}</div>
          <div className={styles.kpiSub}>
            AI call hours × $20/hr — staff freed for floor service
          </div>
        </div>

        {/* Monthly Impact — Total Economic Value */}
        <div className={`${styles.kpiCard} ${styles.kpiImpact}`}>
          <div className={styles.kpiTop}>
            <span className={styles.kpiLabel}>Total Monthly Impact</span>
            <span className={styles.kpiBadge}>PHRC + LCS + UV</span>
          </div>
          <div className={`${styles.kpiValue} ${styles.kpiValueLarge}`}>
            {loadingMetrics ? '—' : fmt(m?.monthly_impact ?? 0)}
          </div>
          <div className={styles.kpiSub}>
            {m && m.total_ai_revenue > 0
              ? `${((m.monthly_impact / m.total_ai_revenue) * 100).toFixed(1)}% of AI-processed revenue`
              : 'Total economic value generated by AI'}
          </div>
        </div>
      </div>

      {/* ── Row 2: Supporting KPIs (2행: 보조 KPI) ── */}
      <div className={styles.kpiRowSm}>
        <div className={styles.kpiCardSm}>
          <div className={styles.kpiSmLabel}>{meta.conversionLabel} (LCR)</div>
          <div className={styles.kpiSmValue} style={{ color: '#6366f1' }}>
            {loadingMetrics ? '—' : `${m?.lcr.toFixed(1) ?? 0}%`}
          </div>
          <div className={styles.kpiSmSub}>
            {loadingMetrics ? '' : `${m?.successful_calls ?? 0} orders / ${m?.total_calls ?? 0} calls`}
          </div>
        </div>

        <div className={styles.kpiCardSm}>
          <div className={styles.kpiSmLabel}>Upselling Value (UV)</div>
          <div className={styles.kpiSmValue} style={{ color: '#f59e0b' }}>
            {loadingMetrics ? '—' : fmt(m?.upselling_value ?? 0)}
          </div>
          <div className={styles.kpiSmSub}>15% upsell rate × $5/success</div>
        </div>

        <div className={styles.kpiCardSm}>
          <div className={styles.kpiSmLabel}>Total AI Revenue</div>
          <div className={styles.kpiSmValue} style={{ color: '#16a34a' }}>
            {loadingMetrics ? '—' : fmt(m?.total_ai_revenue ?? 0)}
          </div>
          <div className={styles.kpiSmSub}>Paid orders processed by AI</div>
        </div>

        <div className={styles.kpiCardSm}>
          <div className={styles.kpiSmLabel}>{meta.avgValueLabel}</div>
          <div className={styles.kpiSmValue} style={{ color: '#0369a1' }}>
            {loadingMetrics ? '—' : fmt(m?.avg_ticket ?? 0)}
          </div>
          <div className={styles.kpiSmSub}>Per paid order value</div>
        </div>

        <div className={styles.kpiCardSm}>
          <div className={styles.kpiSmLabel}>Total Calls Handled</div>
          <div className={styles.kpiSmValue} style={{ color: '#334155' }}>
            {loadingMetrics ? '—' : (m?.total_calls ?? 0).toLocaleString()}
          </div>
          <div className={styles.kpiSmSub}>AI-answered this period</div>
        </div>
      </div>

      {/* ── Panels: AI Persona + Live Orders (AI 페르소나 + 실시간 주문) ── */}
      <div className={styles.panels}>
        {/* Left: AI Persona Editor (좌측: AI 페르소나 편집기) */}
        <div className={styles.personaPanel}>
          <div className={styles.panelHeader}>
            <span className={styles.panelIcon}>🤖</span>
            <div>
              <div className={styles.panelTitle}>AI Persona Editor</div>
              <div className={styles.panelDesc}>Manage your AI voice assistant's core identity and today's daily instructions.</div>
            </div>
          </div>

          <div className={styles.personaSection}>
            <div className={styles.personaLabelRow}>
              <span className={styles.personaLabel}>Core AI Persona</span>
              <span className={styles.essentialBadge}>Essential</span>
            </div>
            <p className={styles.personaNote}>Set by your agency. Defines the AI's core identity and cannot be changed from this view.</p>
            <textarea
              className={styles.personaTextarea}
              readOnly
              rows={5}
              value={`You are Sophia, the AI receptionist for "${storeName ?? 'your store'}".
Your primary goal is to assist customers with food/drink orders and table reservations politely and efficiently.
Always speak in a highly cheerful, upbeat, energetic, and welcoming tone. Smile with your voice!`}
            />
          </div>

          <div className={styles.divider}>DAILY OVERRIDE</div>

          <div className={styles.personaSection}>
            <div className={styles.personaLabelRow}>
              <span className={styles.personaLabel}>Daily Instructions</span>
              <span className={styles.tempBadge}>Temporary</span>
            </div>
            <p className={styles.personaNote}>
              Today's specials, sold-out items, or event notes. Highest priority during live calls.
            </p>
            <textarea
              className={styles.personaTextarea}
              rows={3}
              value={dailyInstructions}
              onChange={(e) => setDailyInstructions(e.target.value)}
              placeholder="e.g. Early summer Special 30% off cold drinks!"
            />
            <div className={styles.charCount}>{dailyInstructions.length} characters</div>
            {saveError && <div style={{ color: '#dc2626', fontSize: 12, marginTop: 4 }}>{saveError}</div>}
            <div className={styles.personaBtns}>
              <button
                className={styles.saveBtn}
                onClick={handleSave}
                disabled={saving || dailyInstructions === savedInstructions}
              >
                💾 {saving ? 'Saving...' : 'Save Changes'}
              </button>
              <button
                className={styles.revertBtn}
                onClick={() => setDailyInstructions(savedInstructions)}
                disabled={saving || dailyInstructions === savedInstructions}
              >
                ↺ Revert
              </button>
            </div>
          </div>
        </div>

        {/* Right: Live Call Orders (우측: 실시간 통화 주문) */}
        <div className={styles.ordersPanel}>
          <div className={styles.panelHeader}>
            <span className={styles.panelIcon}>🛒</span>
            <div>
              <div className={styles.panelTitle}>Live Call Orders</div>
              <div className={styles.panelDesc}>Latest 10 orders placed via the AI voice assistant.</div>
            </div>
            {pendingCount > 0 && (
              <span className={styles.pendingBadge} title="Orders fired without payment yet">
                ⚠ {pendingCount} pending payment
              </span>
            )}
            <button
              className={styles.refreshBtn}
              onClick={() => {
                setLoadingOrders(true)
                api.get('/store/orders?limit=10').then((r) => setOrders(r.data)).finally(() => setLoadingOrders(false))
              }}
            >
              ↺ Refresh
            </button>
          </div>

          {loadingOrders ? (
            <div className={styles.loading}>Loading orders...</div>
          ) : orders.length === 0 ? (
            <div className={styles.empty}>No orders yet</div>
          ) : (
            <table className={styles.ordersTable}>
              <thead>
                <tr>
                  <th>ORDER ID</th>
                  <th>CUSTOMER NAME</th>
                  <th>TOTAL AMOUNT</th>
                  <th>STATUS</th>
                  <th>DATE</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((o) => (
                  <tr key={o.id}>
                    <td className={styles.orderId}>#{o.id}</td>
                    <td>{o.customer_email?.split('@')[0] ?? o.customer_phone ?? '—'}</td>
                    <td className={`${styles.orderAmount} ${o.status === 'paid' ? styles.orderAmountPaid : ''}`}>
                      {fmt(o.total_amount)}
                    </td>
                    <td>
                      <span className={`${styles.statusBadge} ${o.status === 'paid' ? styles.statusPaid : styles.statusPending}`}>
                        {o.status}
                      </span>
                    </td>
                    <td className={styles.orderDate}>{fmtDate(o.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Recent Calls — high-frequency operator scan (최근 5통화) */}
      <div className={styles.recentCallsPanel}>
        <div className={styles.panelHeader}>
          <span className={styles.panelIcon}>📞</span>
          <div>
            <div className={styles.panelTitle}>Recent Calls</div>
            <div className={styles.panelDesc}>Latest 5 voice agent calls — tap row to see full transcript</div>
          </div>
          <Link to="/fsr/store/call-history" className={styles.viewAllLink}>View all →</Link>
        </div>

        {loadingCalls ? (
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
    </div>
  )
}
