// Step 4 — Modifier Review. Calls /api/admin/onboarding/preview-yaml and
// renders the detected modifier groups read-only. Edit UI is intentionally
// not exposed here yet; operators can re-extract upstream if a group is
// wrong. The yaml payloads we receive flow forward to Step 5 (POS sync).
// (Step 4 — preview-yaml 호출, 추출된 modifier group을 read-only로 표시.
//  편집 UI는 아직 없음, yaml은 Step 5로 forward)
import { useEffect, useState } from 'react'
import { previewYaml } from '../api/onboardingClient'
import type {
  ModifierGroup, ModifierGroupsYaml, NormalizedMenuItem, RawMenuExtraction,
} from '../types'
import styles from './StepPlaceholder.module.css'

interface Props {
  raw:         RawMenuExtraction | null
  normalized:  NormalizedMenuItem[] | null
  onBack:      () => void
  onContinue:  (preview: { menu_yaml: Record<string, unknown>; modifier_groups_yaml: ModifierGroupsYaml; vertical: string }) => void
}

export default function Step4_ModifierReview({ raw, normalized, onBack, onContinue }: Props) {
  const vertical = (raw?.vertical_guess ?? 'general') as string
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string>('')
  const [menuYaml, setMenuYaml] = useState<Record<string, unknown> | null>(null)
  const [groupsYaml, setGroupsYaml] = useState<ModifierGroupsYaml | null>(null)

  useEffect(() => {
    if (!normalized || normalized.length === 0) {
      setError('No normalized items to preview — go back and re-run extract.')
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError('')
    previewYaml({ items: normalized, vertical })
      .then((res) => {
        if (cancelled) return
        setMenuYaml(res.menu_yaml)
        setGroupsYaml(res.modifier_groups_yaml)
      })
      .catch((e: unknown) => {
        if (cancelled) return
        const msg = e instanceof Error ? e.message : 'Unknown error'
        setError(`Preview failed: ${msg}`)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [normalized, vertical])

  const groups       = groupsYaml?.groups ?? {}
  const groupEntries = Object.entries(groups)

  function handleContinue() {
    if (!menuYaml || !groupsYaml) return
    onContinue({ menu_yaml: menuYaml, modifier_groups_yaml: groupsYaml, vertical })
  }

  return (
    <div className={styles.wrap}>
      <h2 className={styles.heading}>Review modifier groups</h2>
      <p className={styles.sub}>
        These are the groups we detected from your menu. Each option's price
        delta is shown. If something looks wrong, go back to Step 3 and adjust
        the items, or re-extract from a cleaner source.
      </p>

      <div className={styles.facts}>
        <Fact label="Raw rows" value={String(raw?.items.length ?? 0)} />
        <Fact label="Normalized items" value={String(normalized?.length ?? 0)} />
        <Fact
          label="Detected groups"
          value={loading ? '…' : String(groupEntries.length)}
        />
      </div>

      {error && <div style={errorStyle}>{error}</div>}

      {loading && !error && (
        <div style={{ color: '#64748b', fontSize: 14 }}>
          Building modifier preview…
        </div>
      )}

      {!loading && !error && groupEntries.length === 0 && (
        <div style={{ color: '#64748b', fontSize: 14 }}>
          No modifier groups detected for this menu. Continue to POS sync.
        </div>
      )}

      {!loading && groupEntries.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {groupEntries.map(([name, group]) => (
            <GroupCard key={name} name={name} group={group} />
          ))}
        </div>
      )}

      <div className={styles.actions}>
        <button type="button" className={styles.ghost} onClick={onBack}>← Back</button>
        <button
          type="button"
          className={styles.primary}
          onClick={handleContinue}
          disabled={loading || !!error || !menuYaml}
        >
          Continue to POS sync →
        </button>
      </div>
    </div>
  )
}

function GroupCard({ name, group }: { name: string; group: ModifierGroup }) {
  return (
    <div style={cardStyle}>
      <div style={cardHeaderStyle}>
        <strong style={{ fontSize: 15, color: '#0f172a' }}>{name}</strong>
        <span style={badgeStyle}>
          {group.required ? 'Required' : 'Optional'} · min {group.min} / max {group.max}
        </span>
      </div>
      <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
        Applies to: {group.applies_to_categories.join(', ') || '—'}
      </div>
      <table style={tableStyle}>
        <thead>
          <tr>
            <th style={thStyle}>Option</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>Price delta</th>
            <th style={thStyle}>Default</th>
          </tr>
        </thead>
        <tbody>
          {group.options.map((opt) => (
            <tr key={opt.id}>
              <td style={tdStyle}>{opt.en}</td>
              <td style={{ ...tdStyle, textAlign: 'right' }}>
                {opt.price_delta === 0 ? '—' : `+$${opt.price_delta.toFixed(2)}`}
              </td>
              <td style={tdStyle}>{opt.default ? '✓' : ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
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

const cardStyle: React.CSSProperties = {
  background: '#ffffff',
  border: '1px solid #e2e8f0',
  borderRadius: 10,
  padding: '14px 16px',
}
const cardHeaderStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  gap: 12,
}
const badgeStyle: React.CSSProperties = {
  fontSize: 11,
  color: '#475569',
  background: '#f1f5f9',
  padding: '3px 8px',
  borderRadius: 999,
  fontWeight: 600,
}
const tableStyle: React.CSSProperties = {
  width: '100%',
  marginTop: 10,
  borderCollapse: 'collapse',
  fontSize: 13,
}
const thStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '6px 4px',
  borderBottom: '1px solid #e2e8f0',
  fontSize: 11,
  color: '#64748b',
  fontWeight: 700,
  letterSpacing: '0.04em',
  textTransform: 'uppercase',
}
const tdStyle: React.CSSProperties = {
  padding: '8px 4px',
  borderBottom: '1px solid #f1f5f9',
  color: '#0f172a',
}
const errorStyle: React.CSSProperties = {
  background: '#fef2f2',
  border: '1px solid #fecaca',
  color: '#991b1b',
  padding: '10px 12px',
  borderRadius: 8,
  fontSize: 13,
}
