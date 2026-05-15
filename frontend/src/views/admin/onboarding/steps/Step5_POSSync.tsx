// Step 5 — POS Sync.
// Two-stage commit:
//   1. "Dry-run preview" → POST /api/admin/onboarding/finalize {dry_run:true}
//      Returns counts + next_steps without any Supabase / Loyverse writes.
//   2. "Push to Loyverse" → POST /api/admin/onboarding/finalize {dry_run:false}
//      Real Supabase seed + (optional) Loyverse item upsert.
//
// JM Taco validation defaults are pre-filled — the operator can override.
// (Step 5 — 2단계 commit: dry-run 미리보기 → 실제 push)
import { useState } from 'react'
import { finalizeOnboarding } from '../api/onboardingClient'
import type {
  FinalizeRequest, FinalizeResponse, ModifierGroupsYaml,
} from '../types'
import styles from './StepPlaceholder.module.css'

interface Props {
  preview: {
    menu_yaml: Record<string, unknown>
    modifier_groups_yaml: ModifierGroupsYaml
    vertical: string
  } | null
  onBack:     () => void
  onContinue: () => void
}

// JM Taco validation defaults (2026-05-15 mexican-validation run)
// (사용자 매번 안 채워도 되게 prefill)
const DEFAULTS = {
  store_name:        'JM Taco',
  phone_number:      '',
  manager_phone:     '+15037079566',
  loyverse_store_id: 'dd30971d-dbd7-4468-9843-b6c487d140bb',
  business_hours:    '',
}

type RunMode = 'idle' | 'dry-run' | 'pushing'

export default function Step5_POSSync({ preview, onBack, onContinue }: Props) {
  const [storeName, setStoreName]               = useState(DEFAULTS.store_name)
  const [phoneNumber, setPhoneNumber]           = useState(DEFAULTS.phone_number)
  const [managerPhone, setManagerPhone]         = useState(DEFAULTS.manager_phone)
  const [loyverseStoreId, setLoyverseStoreId]   = useState(DEFAULTS.loyverse_store_id)
  const [businessHours, setBusinessHours]       = useState(DEFAULTS.business_hours)
  const [pushToLoyverse, setPushToLoyverse]     = useState(true)
  const [posApiKey, setPosApiKey]               = useState('')

  const [mode, setMode]   = useState<RunMode>('idle')
  const [error, setError] = useState<string>('')
  const [dryResult, setDryResult] = useState<FinalizeResponse | null>(null)
  const [realResult, setRealResult] = useState<FinalizeResponse | null>(null)

  const vertical = preview?.vertical ?? 'general'
  const itemsCount = (preview?.menu_yaml.items as unknown[] | undefined)?.length ?? 0
  const groupsCount = Object.keys(preview?.modifier_groups_yaml.groups ?? {}).length

  const canDryRun = !!preview && storeName.trim() && phoneNumber.trim()
  const canPush   = canDryRun && !!dryResult
                    && (!pushToLoyverse || (posApiKey.trim() && loyverseStoreId.trim()))

  function buildReq(dry: boolean): FinalizeRequest {
    return {
      store_name:           storeName.trim(),
      phone_number:         phoneNumber.trim(),
      manager_phone:        managerPhone.trim() || undefined,
      vertical,
      menu_yaml:            preview!.menu_yaml,
      modifier_groups_yaml: preview!.modifier_groups_yaml as unknown as Record<string, unknown>,
      pos_provider:         pushToLoyverse ? 'loyverse' : undefined,
      pos_api_key:          pushToLoyverse ? posApiKey.trim() : undefined,
      push_to_loyverse:     pushToLoyverse,
      loyverse_store_id:    pushToLoyverse ? loyverseStoreId.trim() : undefined,
      business_hours:       businessHours.trim() || undefined,
      dry_run:              dry,
    }
  }

  async function runDryRun() {
    setError('')
    setRealResult(null)
    setMode('dry-run')
    try {
      const res = await finalizeOnboarding(buildReq(true))
      setDryResult(res)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Unknown error'
      setError(`Dry-run failed: ${msg}`)
    } finally {
      setMode('idle')
    }
  }

  async function runRealPush() {
    setError('')
    setMode('pushing')
    try {
      const res = await finalizeOnboarding(buildReq(false))
      setRealResult(res)
      // Tell the agency sidebar (and any other listener) to re-fetch the
      // store list — the new store should appear immediately without a
      // page reload. Listener lives in the agency Layout/Sidebar.
      // (사이드바 즉시 갱신 — page reload 없이 새 매장 노출)
      window.dispatchEvent(new CustomEvent('stores:invalidate'))
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Unknown error'
      setError(`Push failed: ${msg}`)
    } finally {
      setMode('idle')
    }
  }

  return (
    <div className={styles.wrap}>
      <h2 className={styles.heading}>Sync to your POS</h2>
      <p className={styles.sub}>
        Review the store info and run a dry-run preview first. The dry-run hits
        Supabase only to confirm reachability — no rows are written. Once the
        counts look right, push to Loyverse for the real seed.
      </p>

      <div className={styles.facts}>
        <Fact label="Vertical" value={vertical} />
        <Fact label="Items" value={String(itemsCount)} />
        <Fact label="Modifier groups" value={String(groupsCount)} />
      </div>

      <div style={formGridStyle}>
        <Field
          label="Store name *"
          value={storeName}
          onChange={setStoreName}
          placeholder="JM Taco"
        />
        <Field
          label="Voice phone number * (Twilio)"
          value={phoneNumber}
          onChange={setPhoneNumber}
          placeholder="+1XXXXXXXXXX"
          help="The Twilio number customers call. Webhook is wired post-push."
        />
        <Field
          label="Manager escalation phone"
          value={managerPhone}
          onChange={setManagerPhone}
          placeholder="+15037079566"
        />
        <Field
          label="Loyverse store ID"
          value={loyverseStoreId}
          onChange={setLoyverseStoreId}
          placeholder="UUID from Loyverse Back Office"
          disabled={!pushToLoyverse}
        />
        <div style={{ gridColumn: '1 / -1' }}>
          <label style={labelStyle}>Business hours</label>
          <textarea
            value={businessHours}
            onChange={(e) => setBusinessHours(e.target.value)}
            placeholder="Monday to Friday: 8 AM to 8 PM. Saturday and Sunday: 9 AM to 6 PM."
            rows={2}
            style={{ ...inputStyle, resize: 'vertical', minHeight: 48, fontFamily: 'inherit' }}
          />
          <div style={helpStyle}>
            Free text — voice agent reads this verbatim when callers ask
            about open hours. Optional but recommended.
          </div>
        </div>
        <div style={{ gridColumn: '1 / -1' }}>
          <label style={checkboxRowStyle}>
            <input
              type="checkbox"
              checked={pushToLoyverse}
              onChange={(e) => setPushToLoyverse(e.target.checked)}
            />
            <span>Push items + modifier groups to Loyverse after Supabase seed</span>
          </label>
        </div>
        <Field
          label={pushToLoyverse ? 'Loyverse API access token *' : 'Loyverse API access token'}
          value={posApiKey}
          onChange={setPosApiKey}
          type="password"
          placeholder="Loyverse Back Office → Settings → API Access tokens"
          disabled={!pushToLoyverse}
        />
      </div>

      {error && <div style={errorStyle}>{error}</div>}

      <div style={actionRowStyle}>
        <button
          type="button"
          className={styles.ghost}
          onClick={onBack}
          disabled={mode !== 'idle'}
        >
          ← Back
        </button>
        <div style={{ display: 'flex', gap: 10 }}>
          <button
            type="button"
            className={styles.ghost}
            onClick={runDryRun}
            disabled={!canDryRun || mode !== 'idle'}
            title={!canDryRun ? 'Fill store name and phone number' : ''}
          >
            {mode === 'dry-run' ? 'Running dry-run…' : 'Dry-run preview'}
          </button>
          <button
            type="button"
            className={styles.primary}
            onClick={runRealPush}
            disabled={!canPush || mode !== 'idle'}
            title={!canPush ? 'Run a successful dry-run first' : ''}
          >
            {mode === 'pushing' ? 'Pushing…' : 'Push to Loyverse'}
          </button>
        </div>
      </div>

      {dryResult && (
        <ResultCard
          title="Dry-run preview"
          tone="neutral"
          result={dryResult}
        />
      )}
      {realResult && (
        <ResultCard
          title="Real push complete"
          tone="success"
          result={realResult}
        />
      )}

      {realResult && (
        <div style={actionRowStyle}>
          <span />
          <button type="button" className={styles.primary} onClick={onContinue}>
            Continue to test call →
          </button>
        </div>
      )}
    </div>
  )
}

function ResultCard({
  title, tone, result,
}: { title: string; tone: 'neutral' | 'success'; result: FinalizeResponse }) {
  const counts = (result.counts ?? null) as Record<string, number> | null
  const nextSteps = result.next_steps ?? []
  const loyverse = result.loyverse_push as
    | { created?: number; updated?: number; error?: string; path?: string; status?: number; dry_run?: boolean; summary?: string }
    | undefined

  return (
    <div style={{
      ...resultCardStyle,
      borderColor: tone === 'success' ? '#86efac' : '#cbd5e1',
      background:  tone === 'success' ? '#f0fdf4' : '#f8fafc',
    }}>
      <div style={resultTitleStyle}>{title}</div>
      <div style={{ fontSize: 12, color: '#475569' }}>
        store_id: <code>{String(result.store_id ?? '—')}</code>
      </div>

      {counts && (
        <div style={countsGridStyle}>
          {Object.entries(counts).map(([k, v]) => (
            <div key={k} style={countCellStyle}>
              <div style={countLabelStyle}>{k.replace(/_/g, ' ')}</div>
              <div style={countValueStyle}>{v}</div>
            </div>
          ))}
        </div>
      )}

      {loyverse && (
        <div style={{ marginTop: 12, fontSize: 13, color: '#0f172a' }}>
          <strong>Loyverse:</strong>{' '}
          {loyverse.error
            ? <span style={{ color: '#991b1b' }}>error at {loyverse.path} (HTTP {loyverse.status}) — {loyverse.error}</span>
            : <span>
                {loyverse.summary
                  ?? `created ${loyverse.created ?? 0}, updated ${loyverse.updated ?? 0}${loyverse.dry_run ? ' (dry-run)' : ''}`}
              </span>}
        </div>
      )}

      {nextSteps.length > 0 && (
        <ol style={nextStepsStyle}>
          {nextSteps.map((s, i) => <li key={i}>{s}</li>)}
        </ol>
      )}
    </div>
  )
}

function Field(props: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  help?: string
  type?: 'text' | 'password'
  disabled?: boolean
}) {
  return (
    <div>
      <label style={labelStyle}>{props.label}</label>
      <input
        type={props.type ?? 'text'}
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        placeholder={props.placeholder}
        disabled={props.disabled}
        style={{
          ...inputStyle,
          opacity: props.disabled ? 0.5 : 1,
        }}
      />
      {props.help && <div style={helpStyle}>{props.help}</div>}
    </div>
  )
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.fact}>
      <div className={styles.factLabel}>{label}</div>
      <div className={styles.factValue}>{value}</div>
    </div>
  )
}

const formGridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(2, 1fr)',
  gap: '12px 16px',
  marginTop: 8,
}
const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 11,
  color: '#475569',
  fontWeight: 700,
  letterSpacing: '0.04em',
  textTransform: 'uppercase',
  marginBottom: 6,
}
const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '9px 11px',
  fontSize: 14,
  border: '1px solid #cbd5e1',
  borderRadius: 8,
  background: '#fff',
  color: '#0f172a',
  boxSizing: 'border-box',
}
const helpStyle: React.CSSProperties = {
  fontSize: 12,
  color: '#64748b',
  marginTop: 4,
}
const checkboxRowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  fontSize: 13,
  color: '#0f172a',
}
const actionRowStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  paddingTop: 16,
  borderTop: '1px solid #f1f5f9',
  marginTop: 12,
}
const resultCardStyle: React.CSSProperties = {
  border: '1px solid #cbd5e1',
  borderRadius: 10,
  padding: '14px 16px',
  marginTop: 16,
}
const resultTitleStyle: React.CSSProperties = {
  fontSize: 14,
  fontWeight: 700,
  color: '#0f172a',
  marginBottom: 6,
}
const countsGridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))',
  gap: 8,
  marginTop: 10,
}
const countCellStyle: React.CSSProperties = {
  background: '#fff',
  border: '1px solid #e2e8f0',
  borderRadius: 8,
  padding: '8px 10px',
}
const countLabelStyle: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  color: '#64748b',
  letterSpacing: '0.04em',
  textTransform: 'uppercase',
}
const countValueStyle: React.CSSProperties = {
  fontSize: 18,
  fontWeight: 700,
  color: '#0f172a',
  marginTop: 2,
}
const nextStepsStyle: React.CSSProperties = {
  margin: '12px 0 0 0',
  paddingLeft: 20,
  fontSize: 13,
  color: '#475569',
  lineHeight: 1.6,
}
const errorStyle: React.CSSProperties = {
  background: '#fef2f2',
  border: '1px solid #fecaca',
  color: '#991b1b',
  padding: '10px 12px',
  borderRadius: 8,
  fontSize: 13,
  marginTop: 8,
}
