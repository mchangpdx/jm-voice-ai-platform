// Store Settings page — hourly wage, timezone, busy schedule, emergency override
// (스토어 설정 페이지 — 시급, 타임존, 바쁜 시간대 스케줄, 긴급 오버라이드)
import { Fragment, useEffect, useState } from 'react'
import api from '../../../core/api'
import Skeleton from '../../../components/Skeleton/Skeleton'
import styles from './Settings.module.css'

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const HOURS = Array.from({ length: 24 }, (_, i) => i)

// Schedule [start, end) overlaps hour cell [h, h+1) when both intervals share
// any minute. Times are stored as 'HH:MM' so we compare decimal hours.
const hourIsBusy = (dow: number, hour: number, schedules: BusySchedule[]) =>
  schedules.some((s) => {
    if (s.day_of_week !== dow) return false
    const [sh, sm] = s.start_time.split(':').map(Number)
    const [eh, em] = s.end_time.split(':').map(Number)
    const startDec = sh + sm / 60
    const endDec   = eh + em / 60
    return startDec < hour + 1 && endDec > hour
  })

interface BusySchedule {
  id?: string
  day_of_week: number
  start_time: string
  end_time: string
}

interface StoreSettings {
  hourly_wage: number
  timezone: string
  is_override_busy: boolean
  override_until: string | null
  busy_schedules: BusySchedule[]
  fire_immediate_threshold_cents: number   // Phase 2-B.1.7b — 0 = policy off
  no_show_timeout_minutes: number          // 2026-04-29 — per-store no-show window (1..1440)
}

const US_TIMEZONES = [
  { value: 'America/Los_Angeles', label: 'Pacific (LA/Portland)' },
  { value: 'America/Denver',      label: 'Mountain (Denver)' },
  { value: 'America/Chicago',     label: 'Central (Chicago)' },
  { value: 'America/New_York',    label: 'Eastern (New York)' },
  { value: 'Pacific/Honolulu',    label: 'Hawaii' },
  { value: 'America/Anchorage',   label: 'Alaska' },
]

const OVERRIDE_DURATIONS = [
  { label: '30 min',       minutes: 30  },
  { label: '1 hour',       minutes: 60  },
  { label: '2 hours',      minutes: 120 },
  { label: 'Until I turn off', minutes: null },
]

export default function Settings() {
  const [storeSettings, setStoreSettings] = useState<StoreSettings | null>(null)
  const [loading, setLoading]             = useState(true)
  const [saving, setSaving]               = useState(false)
  const [savedMsg, setSavedMsg]           = useState('')

  // KPI config local state
  const [hourlyWage, setHourlyWage] = useState('')
  const [timezone, setTimezone]     = useState('')

  // Phase 2-B.1.7b — Order Policy state. UI takes dollars; API takes cents.
  // (UI는 달러, API는 센트 단위)
  const [fireThresholdDollars, setFireThresholdDollars] = useState('0')
  const [noShowMinutes, setNoShowMinutes]               = useState('30')
  const [policySaving, setPolicySaving]                 = useState(false)

  // New schedule form state (per day)
  const [addingDay, setAddingDay]   = useState<number | null>(null)
  const [newStart, setNewStart]     = useState('12:00')
  const [newEnd, setNewEnd]         = useState('14:00')
  const [scheduleErr, setScheduleErr] = useState('')

  // Override state
  const [overrideDuration, setOverrideDuration] = useState<number | null>(60)

  useEffect(() => {
    api.get('/store/settings').then((r) => {
      const s: StoreSettings = r.data
      setStoreSettings(s)
      setHourlyWage(String(s.hourly_wage))
      setTimezone(s.timezone)
      // Cents → dollars for the input field. Empty input is rendered as "0".
      // (센트 → 달러 변환, 입력이 비면 "0")
      setFireThresholdDollars(((s.fire_immediate_threshold_cents ?? 0) / 100).toFixed(2))
      setNoShowMinutes(String(s.no_show_timeout_minutes ?? 30))
    }).finally(() => setLoading(false))
  }, [])

  const flash = (msg: string) => {
    setSavedMsg(msg)
    setTimeout(() => setSavedMsg(''), 2500)
  }

  const saveKpiSettings = async () => {
    const wage = parseFloat(hourlyWage)
    if (isNaN(wage) || wage <= 0) return
    setSaving(true)
    try {
      const r = await api.patch('/store/settings', { hourly_wage: wage, timezone })
      setStoreSettings((s) => s ? { ...s, hourly_wage: r.data.hourly_wage, timezone: r.data.timezone } : s)
      flash('Saved!')
    } finally {
      setSaving(false)
    }
  }

  // Save both Order Policy dials in one PATCH:
  //   - fire_immediate_threshold (UI dollars → API cents, 0 = off, max $100)
  //   - no_show_timeout_minutes (1..1440 — 24-hour cap)
  // (한 번의 PATCH로 두 dial 저장 — 임계값 + no-show 시간)
  const savePolicySettings = async () => {
    const dollars = parseFloat(fireThresholdDollars)
    const minutes = parseInt(noShowMinutes, 10)
    if (isNaN(dollars) || dollars < 0)              return
    if (isNaN(minutes) || minutes < 1 || minutes > 1440) return
    const cents = Math.round(dollars * 100)
    if (cents > 10000) return
    setPolicySaving(true)
    try {
      const r = await api.patch('/store/settings', {
        fire_immediate_threshold_cents: cents,
        no_show_timeout_minutes:        minutes,
      })
      setStoreSettings((s) => s ? {
        ...s,
        fire_immediate_threshold_cents: r.data.fire_immediate_threshold_cents,
        no_show_timeout_minutes:        r.data.no_show_timeout_minutes,
      } : s)
      flash('Order policy saved!')
    } finally {
      setPolicySaving(false)
    }
  }

  const addSchedule = async (dayOfWeek: number) => {
    if (newStart >= newEnd) { setScheduleErr('End time must be after start time'); return }
    setScheduleErr('')
    try {
      const r = await api.post('/store/busy-schedule', {
        day_of_week: dayOfWeek, start_time: newStart, end_time: newEnd,
      })
      setStoreSettings((s) => s
        ? { ...s, busy_schedules: [...s.busy_schedules, r.data].sort((a, b) =>
            a.day_of_week !== b.day_of_week ? a.day_of_week - b.day_of_week
            : a.start_time.localeCompare(b.start_time)) }
        : s)
      setAddingDay(null)
      setNewStart('12:00')
      setNewEnd('14:00')
    } catch { setScheduleErr('Failed to save') }
  }

  const deleteSchedule = async (id: string) => {
    await api.delete(`/store/busy-schedule/${id}`)
    setStoreSettings((s) => s
      ? { ...s, busy_schedules: s.busy_schedules.filter((x) => x.id !== id) }
      : s)
  }

  const setOverride = async (active: boolean) => {
    setSaving(true)
    try {
      const payload: Record<string, unknown> = { active }
      if (active && overrideDuration) payload.duration_minutes = overrideDuration
      const r = await api.post('/store/busy-override', payload)
      setStoreSettings((s) => s
        ? { ...s, is_override_busy: r.data.is_override_busy, override_until: r.data.override_until }
        : s)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className={styles.page}>
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className={styles.section}>
            <Skeleton w={220} h={16} />
            <div style={{ height: 14 }} />
            <Skeleton h={120} radius={8} />
          </div>
        ))}
      </div>
    )
  }
  if (!storeSettings) return null

  const isOverrideActive = storeSettings.is_override_busy

  return (
    <div className={styles.page}>
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Settings</h1>
        <p className={styles.pageDesc}>Manage your store's KPI parameters and busy hour schedule.</p>
      </div>

      {savedMsg && <div className={styles.toast}>{savedMsg}</div>}

      {/* ── Section 1: KPI Configuration (KPI 설정) ── */}
      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <span className={styles.sectionIcon}>⚙️</span>
          <div>
            <div className={styles.sectionTitle}>KPI Configuration</div>
            <div className={styles.sectionDesc}>Values used to calculate Labor Cost Savings (LCS) and other KPIs.</div>
          </div>
        </div>

        <div className={styles.fieldRow}>
          <div className={styles.fieldGroup}>
            <label className={styles.fieldLabel}>Staff Hourly Wage (USD)</label>
            <div className={styles.inputPrefix}>
              <span className={styles.prefix}>$</span>
              <input
                className={styles.input}
                type="number"
                min="1"
                max="999"
                step="0.50"
                value={hourlyWage}
                onChange={(e) => setHourlyWage(e.target.value)}
              />
            </div>
            <p className={styles.fieldHint}>Used to calculate LCS = (call hours) × this rate</p>
          </div>

          <div className={styles.fieldGroup}>
            <label className={styles.fieldLabel}>Store Timezone</label>
            <select
              className={styles.select}
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
            >
              {US_TIMEZONES.map((tz) => (
                <option key={tz.value} value={tz.value}>{tz.label}</option>
              ))}
            </select>
            <p className={styles.fieldHint}>Used for "Today" period filter boundary</p>
          </div>
        </div>

        <button className={styles.saveBtn} onClick={saveKpiSettings} disabled={saving}>
          💾 {saving ? 'Saving…' : 'Save KPI Settings'}
        </button>
      </div>

      {/* ── Section 1.5: Order Policy — fire_immediate threshold (주문 정책) ── */}
      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <span className={styles.sectionIcon}>🍳</span>
          <div>
            <div className={styles.sectionTitle}>Order Policy — Fire-Immediate Threshold</div>
            <div className={styles.sectionDesc}>
              Tickets <strong>under</strong> this amount go straight to the kitchen and the customer
              gets a payment link by SMS. Tickets <strong>at or above</strong> require payment before
              the kitchen sees them. Set <strong>$0</strong> to require payment first for every order.
            </div>
          </div>
        </div>

        <div className={styles.fieldRow}>
          <div className={styles.fieldGroup}>
            <label className={styles.fieldLabel}>Threshold (USD)</label>
            <div className={styles.inputPrefix}>
              <span className={styles.prefix}>$</span>
              <input
                className={styles.input}
                type="number"
                min="0"
                max="100"
                step="1"
                value={fireThresholdDollars}
                onChange={(e) => setFireThresholdDollars(e.target.value)}
              />
            </div>
            <p className={styles.fieldHint}>
              {Number(fireThresholdDollars) > 0
                ? `Orders under $${Number(fireThresholdDollars).toFixed(2)} fire to the kitchen immediately. Larger orders wait for payment.`
                : 'Policy is OFF — every order waits for payment before reaching the kitchen.'}
            </p>
          </div>

          <div className={styles.fieldGroup}>
            <label className={styles.fieldLabel}>No-Show Window (minutes)</label>
            <input
              className={styles.input}
              type="number"
              min="1"
              max="1440"
              step="1"
              value={noShowMinutes}
              onChange={(e) => setNoShowMinutes(e.target.value)}
            />
            <p className={styles.fieldHint}>
              Fire-Immediate orders that go unpaid for this many minutes are
              written off as no-shows. QSR ~15, casual restaurants ~30,
              bakery / pre-orders ~120+. Range: 1–1440 (24 hours).
            </p>
          </div>
        </div>

        <button className={styles.saveBtn} onClick={savePolicySettings} disabled={policySaving}>
          💾 {policySaving ? 'Saving…' : 'Save Order Policy'}
        </button>
      </div>

      {/* ── Section 2: Weekly Busy Schedule (주간 바쁜 시간대 스케줄) ── */}
      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <span className={styles.sectionIcon}>📅</span>
          <div>
            <div className={styles.sectionTitle}>Weekly Busy Schedule</div>
            <div className={styles.sectionDesc}>
              Set your regular peak hours. Calls during these windows are automatically tagged as
              busy — enabling real MCRR data instead of the 20% estimate.
            </div>
          </div>
        </div>

        <div className={styles.heatmapWrap}>
          <div className={styles.heatmap}>
            <div className={styles.heatmapCornerCell} />
            {HOURS.map((h) => (
              <div key={h} className={styles.heatmapHourLabel}>
                {h % 3 === 0 ? h : ''}
              </div>
            ))}
            {DAYS.map((day, dow) => (
              <Fragment key={dow}>
                <button
                  type="button"
                  className={styles.heatmapDayLabel}
                  onClick={() => {
                    document
                      .getElementById(`sched-day-${dow}`)
                      ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
                  }}
                  title={`Jump to ${day} row`}
                >{day}</button>
                {HOURS.map((h) => {
                  const busy = hourIsBusy(dow, h, storeSettings.busy_schedules)
                  return (
                    <div
                      key={h}
                      className={`${styles.heatmapCell} ${busy ? styles.heatmapCellBusy : ''}`}
                      title={`${day} ${String(h).padStart(2, '0')}:00 — ${busy ? 'busy' : 'idle'}`}
                    />
                  )
                })}
              </Fragment>
            ))}
          </div>
          <div className={styles.heatmapLegend}>
            <span className={styles.heatmapLegendItem}>
              <span className={`${styles.heatmapSwatch} ${styles.heatmapSwatchIdle}`} /> Idle
            </span>
            <span className={styles.heatmapLegendItem}>
              <span className={`${styles.heatmapSwatch} ${styles.heatmapSwatchBusy}`} /> Busy
            </span>
            <span className={styles.heatmapHint}>Tap a day label to jump to its row.</span>
          </div>
        </div>

        <div className={styles.scheduleTable}>
          {DAYS.map((day, dow) => {
            const daySchedules = storeSettings.busy_schedules.filter((s) => s.day_of_week === dow)
            const isAdding = addingDay === dow

            return (
              <div key={dow} id={`sched-day-${dow}`} className={styles.scheduleRow}>
                <span className={styles.dayName}>{day}</span>

                <div className={styles.timeSlots}>
                  {daySchedules.map((s) => (
                    <span key={s.id} className={styles.timeSlot}>
                      {s.start_time}–{s.end_time}
                      <button
                        className={styles.slotDelete}
                        onClick={() => s.id && deleteSchedule(s.id)}
                        title="Remove"
                      >✕</button>
                    </span>
                  ))}

                  {isAdding ? (
                    <div className={styles.addForm}>
                      <input
                        type="time"
                        className={styles.timeInput}
                        value={newStart}
                        onChange={(e) => setNewStart(e.target.value)}
                      />
                      <span className={styles.timeSep}>–</span>
                      <input
                        type="time"
                        className={styles.timeInput}
                        value={newEnd}
                        onChange={(e) => setNewEnd(e.target.value)}
                      />
                      <button className={styles.addConfirm} onClick={() => addSchedule(dow)}>OK</button>
                      <button className={styles.addCancel} onClick={() => { setAddingDay(null); setScheduleErr('') }}>✕</button>
                    </div>
                  ) : (
                    <button
                      className={styles.addSlotBtn}
                      onClick={() => { setAddingDay(dow); setScheduleErr('') }}
                    >+ Add</button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
        {scheduleErr && <p className={styles.errorMsg}>{scheduleErr}</p>}
      </div>

      {/* ── Section 3: Emergency Override (긴급 오버라이드) ── */}
      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <span className={styles.sectionIcon}>🚨</span>
          <div>
            <div className={styles.sectionTitle}>Emergency Busy Override</div>
            <div className={styles.sectionDesc}>
              For unexpected rushes outside your scheduled hours — one tap, auto-expires.
            </div>
          </div>
        </div>

        <div className={styles.overridePanel}>
          <div className={`${styles.overrideStatus} ${isOverrideActive ? styles.overrideOn : styles.overrideOff}`}>
            <span className={styles.overrideDot} />
            {isOverrideActive
              ? `Busy mode ON${storeSettings.override_until ? ` until ${new Date(storeSettings.override_until).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}` : ' (manual)'}`
              : 'Normal mode'}
          </div>

          {!isOverrideActive ? (
            <div className={styles.overrideControls}>
              <div className={styles.durationPills}>
                {OVERRIDE_DURATIONS.map((d) => (
                  <button
                    key={d.label}
                    className={`${styles.durationPill} ${overrideDuration === d.minutes ? styles.durationPillActive : ''}`}
                    onClick={() => setOverrideDuration(d.minutes ?? null)}
                  >
                    {d.label}
                  </button>
                ))}
              </div>
              <button
                className={styles.overrideStartBtn}
                onClick={() => setOverride(true)}
                disabled={saving}
              >
                🔴 Start Busy Mode
              </button>
            </div>
          ) : (
            <button
              className={styles.overrideEndBtn}
              onClick={() => setOverride(false)}
              disabled={saving}
            >
              🟢 End Busy Mode
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
