// Analytics — call volume trends, revenue, sentiment, and peak hour heatmap
// (분석 대시보드 — 통화량 트렌드, 매출, 감정 분석, 피크 타임 히트맵)
import { Fragment, useEffect, useState } from 'react'
import {
  AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from 'recharts'
import api from '../../../core/api'
import styles from './Analytics.module.css'

type Period = 'week' | 'month' | 'all'

interface DailyCall    { date: string; successful: number; unsuccessful: number; total: number }
interface HourlyPoint  { hour: number; count: number }
interface DailyRevenue { date: string; revenue: number; orders: number }
interface Summary {
  peak_hour: number; peak_hour_label: string; peak_day: string
  avg_daily_calls: number; total_call_minutes: number; busiest_period: string
}
interface AnalyticsData {
  daily_calls: DailyCall[]
  hourly_distribution: HourlyPoint[]
  daily_revenue: DailyRevenue[]
  sentiment_breakdown: Record<string, number>
  day_of_week_distribution: { day: string; count: number }[]
  summary: Summary
}

const PERIODS: { key: Period; label: string }[] = [
  { key: 'week',  label: 'Last 7 Days' },
  { key: 'month', label: 'Last 30 Days' },
  { key: 'all',   label: 'All Time' },
]

const DAYS_ORDER = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

// Heatmap color scale (light to dark indigo)
function heatmapColor(count: number, max: number): string {
  if (max === 0 || count === 0) return '#f1f5f9'
  const ratio = count / max
  if (ratio < 0.2)  return '#e0e7ff'
  if (ratio < 0.4)  return '#c7d2fe'
  if (ratio < 0.6)  return '#a5b4fc'
  if (ratio < 0.75) return '#818cf8'
  if (ratio < 0.9)  return '#6366f1'
  return '#4338ca'
}

// Custom tooltip for recharts (차트 툴팁)
function CallTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div style={{ background: '#0f172a', border: 'none', borderRadius: 8, padding: '8px 12px' }}>
      <p style={{ color: '#94a3b8', fontSize: 12, margin: '0 0 4px' }}>{label}</p>
      {payload.map((p: any) => (
        <p key={p.name} style={{ color: p.color, fontSize: 13, margin: '2px 0', fontWeight: 600 }}>
          {p.name}: {p.value}
        </p>
      ))}
    </div>
  )
}

function RevenueTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div style={{ background: '#0f172a', border: 'none', borderRadius: 8, padding: '8px 12px' }}>
      <p style={{ color: '#94a3b8', fontSize: 12, margin: '0 0 4px' }}>{label}</p>
      <p style={{ color: '#4ade80', fontSize: 13, margin: '2px 0', fontWeight: 600 }}>
        Revenue: ${payload[0]?.value?.toFixed(2)}
      </p>
      <p style={{ color: '#94a3b8', fontSize: 12, margin: '2px 0' }}>
        {payload[0]?.payload?.orders} orders
      </p>
    </div>
  )
}

// Sentiment donut SVG (SVG 도넛 차트)
function SentimentDonut({ positive, neutral, negative }: { positive: number; neutral: number; negative: number }) {
  const total = positive + neutral + negative || 1
  const cx = 60, cy = 60, r = 44, stroke = 14
  const circ = 2 * Math.PI * r

  const segs = [
    { pct: positive / total, color: '#6366f1', label: 'Positive' },
    { pct: neutral  / total, color: '#94a3b8', label: 'Neutral'  },
    { pct: negative / total, color: '#f59e0b', label: 'Negative' },
  ]

  let offset = 0
  const slices = segs.map((s) => {
    const dash   = s.pct * circ
    const gap    = circ - dash
    const result = { ...s, dashArray: `${dash} ${gap}`, dashOffset: -offset * circ }
    offset += s.pct
    return result
  })

  return (
    <svg width={120} height={120} className={styles.donutWrap}>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="#f1f5f9" strokeWidth={stroke} />
      {slices.map((s) => (
        <circle
          key={s.label}
          cx={cx} cy={cy} r={r}
          fill="none"
          stroke={s.color}
          strokeWidth={stroke}
          strokeDasharray={s.dashArray}
          strokeDashoffset={s.dashOffset}
          transform={`rotate(-90 ${cx} ${cy})`}
          style={{ transition: 'all .5s' }}
        />
      ))}
      <text x={cx} y={cy - 6}  textAnchor="middle" fontSize={18} fontWeight={700} fill="#0f172a">
        {Math.round((positive / total) * 100)}%
      </text>
      <text x={cx} y={cy + 12} textAnchor="middle" fontSize={10} fill="#94a3b8">Positive</text>
    </svg>
  )
}

export default function Analytics({ apiEndpoint = '/store/analytics' }: { apiEndpoint?: string }) {
  const [period,  setPeriod]  = useState<Period>('month')
  const [data,    setData]    = useState<AnalyticsData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    api.get(`${apiEndpoint}?period=${period}`)
      .then((r) => setData(r.data))
      .finally(() => setLoading(false))
  }, [apiEndpoint, period])

  const s   = data?.summary
  const sen = data?.sentiment_breakdown ?? {}
  const pos = sen.Positive ?? 0
  const neu = sen.Neutral  ?? 0
  const neg = sen.Negative ?? 0
  const senTotal = pos + neu + neg || 1

  // Build heatmap: rows=7 days (Mon-Sun), cols=24 hours
  // (히트맵: 7일 × 24시간 격자)
  const hourlyMap: Record<number, number> = {}
  ;(data?.hourly_distribution ?? []).forEach((h) => { hourlyMap[h.hour] = h.count })

  // Since we only have overall hourly data, distribute evenly across days for visualization
  // (일별 데이터가 없으므로 요일 × 시간 격자는 hourly + DOW weight로 추정)
  const dowMap: Record<string, number> = {}
  ;(data?.day_of_week_distribution ?? []).forEach((d) => { dowMap[d.day] = d.count })
  const dowTotal = Math.max(Object.values(dowMap).reduce((a, b) => a + b, 0), 1)

  function heatVal(day: string, hour: number): number {
    const dayWeight   = (dowMap[day] ?? 0) / dowTotal
    const hourVal     = hourlyMap[hour] ?? 0
    return Math.round(hourVal * dayWeight * 7)  // scale to visible range
  }

  const maxHeatVal = Math.max(
    ...DAYS_ORDER.flatMap((d) => Array.from({ length: 24 }, (_, h) => heatVal(d, h)))
  )

  // Format date labels for charts (차트용 날짜 레이블)
  function shortDate(iso: string) {
    try {
      return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    } catch { return iso }
  }

  const dailyCallsData  = (data?.daily_calls ?? []).map((d) => ({ ...d, date: shortDate(d.date) }))
  const dailyRevenueData = (data?.daily_revenue ?? []).map((d) => ({ ...d, date: shortDate(d.date) }))
  const dowData = DAYS_ORDER.map((d) => ({ day: d, count: dowMap[d] ?? 0 }))
  const maxDow  = Math.max(...dowData.map((d) => d.count), 1)

  return (
    <div className={styles.page}>
      {/* Header (헤더) */}
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Analytics</h1>
        <p className={styles.pageDesc}>Call volume trends, revenue performance, and peak hour insights.</p>
      </div>

      {/* Period filter (기간 필터) */}
      <div className={styles.periodRow}>
        <span className={styles.periodLabel}>Period:</span>
        {PERIODS.map(({ key, label }) => (
          <button
            key={key}
            className={`${styles.periodBtn} ${period === key ? styles.periodBtnActive : ''}`}
            onClick={() => setPeriod(key)}
          >{label}</button>
        ))}
      </div>

      {/* ── Insight summary cards (요약 인사이트 카드) ── */}
      <div className={styles.insightRow}>
        <div className={styles.insightCard}>
          <div className={`${styles.insightIcon} ${styles.iconPurple}`}>📞</div>
          <div className={styles.insightContent}>
            <div className={styles.insightLabel}>Avg Daily Calls</div>
            <div className={styles.insightValue}>{loading ? '—' : s?.avg_daily_calls ?? 0}</div>
            <div className={styles.insightSub}>calls per day</div>
          </div>
        </div>

        <div className={styles.insightCard}>
          <div className={`${styles.insightIcon} ${styles.iconAmber}`}>⏰</div>
          <div className={styles.insightContent}>
            <div className={styles.insightLabel}>Peak Hour</div>
            <div className={styles.insightValue}>{loading ? '—' : s?.peak_hour_label ?? '—'}</div>
            <div className={styles.insightSub}>{loading ? '' : s?.busiest_period} rush</div>
          </div>
        </div>

        <div className={styles.insightCard}>
          <div className={`${styles.insightIcon} ${styles.iconGreen}`}>📅</div>
          <div className={styles.insightContent}>
            <div className={styles.insightLabel}>Busiest Day</div>
            <div className={styles.insightValue}>{loading ? '—' : s?.peak_day ?? '—'}</div>
            <div className={styles.insightSub}>most calls this period</div>
          </div>
        </div>

        <div className={styles.insightCard}>
          <div className={`${styles.insightIcon} ${styles.iconBlue}`}>🎙️</div>
          <div className={styles.insightContent}>
            <div className={styles.insightLabel}>Total AI Talk Time</div>
            <div className={styles.insightValue}>
              {loading ? '—' : `${Math.round((s?.total_call_minutes ?? 0) / 60)}h`}
            </div>
            <div className={styles.insightSub}>{loading ? '' : `${Math.round(s?.total_call_minutes ?? 0).toLocaleString()} minutes`}</div>
          </div>
        </div>
      </div>

      {/* ── Call Volume Trend (통화량 트렌드) ── */}
      <div className={styles.chartCardFull}>
        <p className={styles.chartTitle}>Call Volume Trend</p>
        <p className={styles.chartSub}>Daily AI-handled calls — successful orders vs unsuccessful inquiries</p>
        {loading ? (
          <div className={styles.skeleton} style={{ height: 200 }} />
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={dailyCallsData} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="gradSucc" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#6366f1" stopOpacity={0.25} />
                  <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="gradUnsucc" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#94a3b8" stopOpacity={0.15} />
                  <stop offset="95%" stopColor="#94a3b8" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#94a3b8' }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} tickLine={false} axisLine={false} />
              <Tooltip content={<CallTooltip />} />
              <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
              <Area type="monotone" dataKey="successful"   name="Successful"   stroke="#6366f1" strokeWidth={2} fill="url(#gradSucc)"   dot={false} />
              <Area type="monotone" dataKey="unsuccessful" name="Unsuccessful" stroke="#94a3b8" strokeWidth={1.5} fill="url(#gradUnsucc)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* ── Two column charts (2열 차트) ── */}
      <div className={styles.chartGrid}>
        {/* Revenue Trend (매출 트렌드) */}
        <div className={styles.chartCard}>
          <p className={styles.chartTitle}>Daily Revenue</p>
          <p className={styles.chartSub}>Paid orders revenue per day ($)</p>
          {loading ? (
            <div className={styles.skeleton} style={{ height: 180 }} />
          ) : (
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={dailyRevenueData} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#94a3b8' }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
                <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} tickLine={false} axisLine={false} tickFormatter={(v) => `$${v}`} />
                <Tooltip content={<RevenueTooltip />} />
                <Bar dataKey="revenue" name="Revenue" fill="#4ade80" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Sentiment breakdown (감정 분석) */}
        <div className={styles.chartCard}>
          <p className={styles.chartTitle}>Customer Sentiment</p>
          <p className={styles.chartSub}>How customers felt during AI calls</p>
          {loading ? (
            <div className={styles.skeleton} style={{ height: 180 }} />
          ) : (
            <div className={styles.sentimentWrap}>
              <SentimentDonut positive={pos} neutral={neu} negative={neg} />
              <div className={styles.sentimentLegend}>
                {[
                  { label: 'Positive', count: pos, color: '#6366f1' },
                  { label: 'Neutral',  count: neu, color: '#94a3b8' },
                  { label: 'Negative', count: neg, color: '#f59e0b' },
                ].map(({ label, count, color }) => (
                  <div key={label} className={styles.legendRow}>
                    <div className={styles.legendDot} style={{ background: color }} />
                    <span className={styles.legendLabel}>{label}</span>
                    <span className={styles.legendPct}>{Math.round(count / senTotal * 100)}%</span>
                    <span className={styles.legendCount}>({count.toLocaleString()})</span>
                  </div>
                ))}
                <div style={{ marginTop: 4, fontSize: 11, color: '#94a3b8' }}>
                  Total: {senTotal.toLocaleString()} calls rated
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Day-of-week + Peak Hour Heatmap (요일별 + 피크 시간 히트맵) ── */}
      <div className={styles.chartGrid}>
        {/* Day of week (요일별 분포) */}
        <div className={styles.chartCard}>
          <p className={styles.chartTitle}>Calls by Day of Week</p>
          <p className={styles.chartSub}>Which days your AI handles the most calls</p>
          {loading ? (
            <div className={styles.skeleton} style={{ height: 120 }} />
          ) : (
            <div className={styles.dowChart}>
              {dowData.map(({ day, count }) => (
                <div key={day} className={styles.dowBar}>
                  <div className={styles.dowBarValue}>{count > 0 ? count : ''}</div>
                  <div
                    className={styles.dowBarFill}
                    style={{ height: `${Math.round((count / maxDow) * 72)}px`, background: day === s?.peak_day ? '#6366f1' : '#a5b4fc' }}
                  />
                  <div className={styles.dowBarLabel}>{day}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Peak hour summary (피크 시간 요약) */}
        <div className={styles.chartCard}>
          <p className={styles.chartTitle}>Hourly Call Distribution</p>
          <p className={styles.chartSub}>Volume across hours (local Portland time)</p>
          {loading ? (
            <div className={styles.skeleton} style={{ height: 120 }} />
          ) : (
            <ResponsiveContainer width="100%" height={130}>
              <BarChart data={data?.hourly_distribution.map((h) => ({
                hour: h.hour < 12 ? `${h.hour === 0 ? 12 : h.hour}AM`
                      : h.hour === 12 ? '12PM'
                      : `${h.hour - 12}PM`,
                count: h.count,
              }))} margin={{ top: 5, right: 5, left: -25, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                <XAxis dataKey="hour" tick={{ fontSize: 9, fill: '#94a3b8' }} tickLine={false} axisLine={false} interval={2} />
                <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} />
                <Tooltip contentStyle={{ background: '#0f172a', border: 'none', borderRadius: 8, fontSize: 12, color: '#fff' }} />
                <Bar dataKey="count" name="Calls" fill="#6366f1" radius={[2, 2, 0, 0]} opacity={0.8} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* ── Peak Hour Heatmap (피크 시간 히트맵: 요일 × 시간) ── */}
      <div className={styles.chartCardFull}>
        <p className={styles.chartTitle}>Peak Hour Heatmap</p>
        <p className={styles.chartSub}>
          Call density by hour and day of week — darker = more calls (통화 밀도 히트맵)
        </p>
        {loading ? (
          <div className={styles.skeleton} style={{ height: 220 }} />
        ) : (
          <div className={styles.heatmapOuter}>
            <div className={styles.heatmap}>
              {/* Hour header row (시간 헤더 행) */}
              <div style={{ gridColumn: 1, gridRow: 1 }} />
              {Array.from({ length: 24 }, (_, h) => (
                <div key={h} className={styles.heatmapHourLabel} style={{ gridColumn: h + 2, gridRow: 1 }}>
                  {h === 0 ? '12a' : h < 12 ? `${h}a` : h === 12 ? '12p' : `${h - 12}p`}
                </div>
              ))}

              {/* Day rows (요일 행) */}
              {DAYS_ORDER.map((day, di) => (
                <Fragment key={day}>
                  <div className={styles.heatmapDayLabel} style={{ gridColumn: 1, gridRow: di + 2 }}>
                    {day}
                  </div>
                  {Array.from({ length: 24 }, (_, h) => {
                    const val = heatVal(day, h)
                    return (
                      <div
                        key={`${day}-${h}`}
                        className={styles.heatmapCell}
                        style={{
                          gridColumn: h + 2,
                          gridRow: di + 2,
                          background: heatmapColor(val, maxHeatVal),
                        }}
                        data-tip={`${day} ${h < 12 ? `${h === 0 ? 12 : h}AM` : h === 12 ? '12PM' : `${h - 12}PM`}: ~${val} calls`}
                      />
                    )
                  })}
                </Fragment>
              ))}
            </div>

            {/* Heatmap legend (히트맵 범례) */}
            <div className={styles.heatmapLegend}>
              <span>Low</span>
              <div className={styles.heatmapLegendBar}>
                {['#f1f5f9','#e0e7ff','#c7d2fe','#a5b4fc','#818cf8','#6366f1','#4338ca'].map((c, i) => (
                  <div key={i} className={styles.heatmapLegendSwatch} style={{ background: c }} />
                ))}
              </div>
              <span>High</span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
