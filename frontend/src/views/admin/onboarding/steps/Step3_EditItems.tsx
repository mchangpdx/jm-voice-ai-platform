// Step 3 — Edit Items: inline edit, bulk remove low-confidence rows,
// then POST /normalize to fold size variants under a single item.
// (Step 3 — 인라인 편집 + 정규화)
// UI copy: English only per [[feedback-ui-language-english-only]].
import { useMemo, useState } from 'react'
import ConfidenceBadge from '../components/ConfidenceBadge'
import { normalizeMenu } from '../api/onboardingClient'
import type { RawMenuExtraction, RawMenuItem, NormalizedMenuItem } from '../types'
import styles from './Step3_EditItems.module.css'

interface Props {
  raw: RawMenuExtraction
  onBack: () => void
  onNormalized: (items: NormalizedMenuItem[]) => void
}

export default function Step3_EditItems({ raw, onBack, onNormalized }: Props) {
  const [items, setItems] = useState<RawMenuItem[]>(raw.items)
  const [working, setWorking] = useState(false)
  const [err, setErr] = useState('')

  const lowCount = useMemo(
    () => items.filter((i) => i.confidence < 0.70).length,
    [items],
  )
  const invalidCount = useMemo(
    () => items.filter((i) => !i.name.trim() || i.price <= 0).length,
    [items],
  )

  function update(i: number, patch: Partial<RawMenuItem>) {
    setItems((prev) => prev.map((r, idx) => idx === i ? { ...r, ...patch } : r))
  }
  function removeRow(i: number) {
    setItems((prev) => prev.filter((_, idx) => idx !== i))
  }
  function removeAllLow() {
    setItems((prev) => prev.filter((i) => i.confidence >= 0.70))
  }
  function resetAll() {
    setItems(raw.items)
  }

  async function onNormalize() {
    setErr('')
    if (invalidCount > 0) {
      setErr(`${invalidCount} ${invalidCount === 1 ? 'item is' : 'items are'} missing a name or price.`)
      return
    }
    setWorking(true)
    try {
      const normalized = await normalizeMenu({ ...raw, items })
      onNormalized(normalized)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Unknown error'
      setErr(`Normalize failed: ${msg}`)
    } finally {
      setWorking(false)
    }
  }

  return (
    <div className={styles.wrap}>
      <header>
        <h2 className={styles.heading}>Review and edit items</h2>
        <p className={styles.sub}>
          Click any cell to edit. Remove items you don't want.
          We will automatically fold size variants in the next step.
        </p>
      </header>

      <div className={styles.toolbar}>
        <div className={styles.stats}>
          <span className={styles.statPill}>
            <strong>{items.length}</strong> items
          </span>
          {lowCount > 0 && (
            <span className={`${styles.statPill} ${styles.statPillLow}`}>
              <strong>{lowCount}</strong> low confidence
            </span>
          )}
          {items.length !== raw.items.length && (
            <span className={`${styles.statPill} ${styles.statPillEdited}`}>
              {raw.items.length - items.length} removed
            </span>
          )}
        </div>
        <div className={styles.bulkActions}>
          {lowCount > 0 && (
            <button type="button" className={styles.linkBtn} onClick={removeAllLow}>
              Remove all low-confidence items
            </button>
          )}
          {items.length !== raw.items.length && (
            <button type="button" className={styles.linkBtn} onClick={resetAll}>
              Reset to original
            </button>
          )}
        </div>
      </div>

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Item name</th>
              <th>Size</th>
              <th style={{ width: 110 }}>Price (USD)</th>
              <th>Category</th>
              <th>Allergens</th>
              <th>Confidence</th>
              <th style={{ width: 40 }} aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr><td colSpan={7} className={styles.empty}>
                All items removed. Go back to start over.
              </td></tr>
            ) : items.map((it, i) => {
              const nameInvalid = !it.name.trim()
              const priceInvalid = it.price <= 0
              return (
                <tr key={i}>
                  <td>
                    <input
                      className={`${styles.cell} ${nameInvalid ? styles.cellInvalid : ''}`}
                      value={it.name}
                      onChange={(e) => update(i, { name: e.target.value })}
                      placeholder="Item name"
                    />
                  </td>
                  <td>
                    <input
                      className={styles.cell}
                      value={it.size_hint ?? ''}
                      onChange={(e) => update(i, { size_hint: e.target.value || null })}
                      placeholder="—"
                    />
                  </td>
                  <td>
                    <input
                      className={`${styles.cell} ${priceInvalid ? styles.cellInvalid : ''}`}
                      type="number"
                      min={0}
                      step="0.01"
                      value={it.price || ''}
                      onChange={(e) => update(i, { price: parseFloat(e.target.value) || 0 })}
                      placeholder="0.00"
                    />
                  </td>
                  <td>
                    <input
                      className={styles.cell}
                      value={it.category ?? ''}
                      onChange={(e) => update(i, { category: e.target.value || null })}
                      placeholder="—"
                    />
                  </td>
                  <td>
                    <input
                      className={styles.cell}
                      value={(it.detected_allergens ?? []).join(', ')}
                      onChange={(e) => {
                        const list = e.target.value
                          .split(',')
                          .map((s) => s.trim())
                          .filter(Boolean)
                        update(i, { detected_allergens: list.length ? list : null })
                      }}
                      placeholder="gluten, dairy"
                    />
                  </td>
                  <td><ConfidenceBadge confidence={it.confidence} /></td>
                  <td>
                    <button
                      type="button"
                      className={styles.delBtn}
                      onClick={() => removeRow(i)}
                      aria-label={`Remove ${it.name || 'row'}`}
                    >✕</button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {err && <div className={styles.err} role="alert">{err}</div>}

      <div className={styles.actions}>
        <button type="button" className={styles.ghost} onClick={onBack}>
          ← Back
        </button>
        <button
          type="button"
          className={styles.primary}
          onClick={onNormalize}
          disabled={working || items.length === 0}
        >
          {working ? 'Normalizing…' : 'Continue to modifiers →'}
        </button>
      </div>
    </div>
  )
}
