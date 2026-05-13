// Step 3 — Edit Items: inline edit name/price/category/allergens, delete rows,
// then POST /normalize to fold size variants under a single item.
// (Step 3 — 인라인 편집 + 정규화)
import { useState } from 'react'
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

  function update(i: number, patch: Partial<RawMenuItem>) {
    setItems((prev) => prev.map((r, idx) => idx === i ? { ...r, ...patch } : r))
  }
  function removeRow(i: number) {
    setItems((prev) => prev.filter((_, idx) => idx !== i))
  }

  async function onNormalize() {
    setErr('')
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
        <h2 className={styles.heading}>
          Edit items <span className={styles.headingKo}>(항목 편집)</span>
        </h2>
        <p className={styles.sub}>
          Click any cell to edit. Remove rows you don't want. We will fold size variants in the next step.
          <br />
          <span className={styles.subKo}>
            셀을 클릭해 수정하세요. 불필요한 행은 삭제. 사이즈 변형은 다음 단계에서 자동으로 묶입니다.
          </span>
        </p>
      </header>

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Size</th>
              <th style={{ width: 110 }}>Price ($)</th>
              <th>Category</th>
              <th>Allergens</th>
              <th>Conf.</th>
              <th style={{ width: 40 }} />
            </tr>
          </thead>
          <tbody>
            {items.map((it, i) => (
              <tr key={i}>
                <td>
                  <input
                    className={styles.cell}
                    value={it.name}
                    onChange={(e) => update(i, { name: e.target.value })}
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
                    className={styles.cell}
                    type="number"
                    min={0}
                    step="0.01"
                    value={it.price}
                    onChange={(e) => update(i, { price: parseFloat(e.target.value) || 0 })}
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
                    aria-label={`Remove ${it.name}`}
                  >✕</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {err && <div className={styles.err}>{err}</div>}

      <div className={styles.actions}>
        <button type="button" className={styles.ghost} onClick={onBack}>
          ← Back (뒤로)
        </button>
        <div className={styles.actionRight}>
          <span className={styles.count}>{items.length} items</span>
          <button
            type="button"
            className={styles.primary}
            onClick={onNormalize}
            disabled={working || items.length === 0}
          >
            {working ? 'Normalizing…' : 'Normalize → Modifiers (다음)'}
          </button>
        </div>
      </div>
    </div>
  )
}
