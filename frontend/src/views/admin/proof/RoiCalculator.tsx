// Interactive ROI calculator — sliders + numeric inputs, real-time monthly/annual savings.
// (인터랙티브 ROI 계산기 — 슬라이더 입력, 월/연 절감액 + payback 실시간 계산)
import { useMemo, useState } from 'react'
import { ROI_DEFAULTS } from '../proofConstants'
import styles from '../ArchitectureProof.module.css'

interface SliderRowProps {
  label:  string
  value:  number
  min:    number
  max:    number
  step:   number
  unit?:  string
  onChange: (n: number) => void
}

function SliderRow({ label, value, min, max, step, unit, onChange }: SliderRowProps) {
  return (
    <div className={styles.roiInputRow}>
      <label className={styles.roiInputLabel}>
        <span>{label}</span>
        <span className={styles.roiInputValue}>{value.toLocaleString()}{unit ? ` ${unit}` : ''}</span>
      </label>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className={styles.roiSlider}
      />
    </div>
  )
}

const fmt$ = (n: number) =>
  `$${Math.round(n).toLocaleString('en-US')}`

export default function RoiCalculator() {
  const [calls,    setCalls]    = useState(ROI_DEFAULTS.callsPerMonth)
  const [ticket,   setTicket]   = useState(ROI_DEFAULTS.avgTicketUsd)
  const [conv,     setConv]     = useState(ROI_DEFAULTS.conversionRatePct)
  const [hourly,   setHourly]   = useState(ROI_DEFAULTS.staffHourlyUsd)
  const [minutes,  setMinutes]  = useState(ROI_DEFAULTS.minutesPerCall)
  const [jm,       setJm]       = useState(ROI_DEFAULTS.jmMonthlyUsd)

  const results = useMemo(() => {
    const revenueMonthly = calls * (conv / 100) * ticket
    const staffSavingsMonthly = calls * (minutes / 60) * hourly
    const grossMonthly = revenueMonthly + staffSavingsMonthly
    const netMonthly = grossMonthly - jm
    const netAnnual  = netMonthly * 12
    const paybackDays = grossMonthly > 0
      ? Math.max(0, Math.round((jm / grossMonthly) * 30))
      : 0
    return { revenueMonthly, staffSavingsMonthly, grossMonthly, netMonthly, netAnnual, paybackDays }
  }, [calls, ticket, conv, hourly, minutes, jm])

  return (
    <>
      <p className={styles.sectionSub}>
        Move the sliders to match your store. The right panel updates in real time. Defaults are
        intentionally conservative for an SMB single-location baseline.
      </p>

      <div className={styles.roiLayout}>
        <div className={styles.roiInputs}>
          <SliderRow label="Inbound calls / month"    value={calls}   min={50}   max={2000} step={10}  onChange={setCalls} />
          <SliderRow label="Average ticket"            value={ticket}  min={5}    max={120}  step={1}   unit="USD" onChange={setTicket} />
          <SliderRow label="Conversion rate"           value={conv}    min={5}    max={80}   step={1}   unit="%"   onChange={setConv} />
          <SliderRow label="Staff hourly wage"         value={hourly}  min={12}   max={50}   step={1}   unit="USD" onChange={setHourly} />
          <SliderRow label="Staff minutes saved / call" value={minutes} min={1}    max={10}   step={0.5} unit="min" onChange={setMinutes} />
          <SliderRow label="JM monthly subscription"   value={jm}      min={99}   max={999}  step={10}  unit="USD" onChange={setJm} />
        </div>

        <div className={styles.roiResults}>
          <div className={styles.roiResultMain}>
            <div className={styles.roiResultLabel}>Annual net savings</div>
            <div className={styles.roiResultNum} style={{ color: results.netAnnual >= 0 ? '#16a34a' : '#dc2626' }}>
              {fmt$(results.netAnnual)}
            </div>
          </div>

          <div className={styles.roiResultGrid}>
            <div>
              <span>Revenue captured</span>
              <strong>{fmt$(results.revenueMonthly)}<small>/mo</small></strong>
            </div>
            <div>
              <span>Staff time saved</span>
              <strong>{fmt$(results.staffSavingsMonthly)}<small>/mo</small></strong>
            </div>
            <div>
              <span>Net monthly</span>
              <strong>{fmt$(results.netMonthly)}</strong>
            </div>
            <div>
              <span>Payback period</span>
              <strong>{results.paybackDays} <small>days</small></strong>
            </div>
          </div>
        </div>
      </div>

      <p className={styles.chartFootnote}>
        Revenue assumes captured calls would otherwise be missed. Staff savings counts time freed for
        higher-value work. Both are illustrative — your mileage will vary by vertical and seasonality.
      </p>
    </>
  )
}
