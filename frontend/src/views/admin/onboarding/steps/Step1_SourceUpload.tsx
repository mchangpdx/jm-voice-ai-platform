// Step 1 — Source Upload: pick a source type and provide input.
// (Step 1 — 소스 업로드)
//
// Five source types, each with its own input UI:
//   loyverse  → API key + Verify
//   url       → URL text input
//   image     → drag-drop multiple files (path stub for now)
//   csv       → drag-drop single file
//   manual    → spreadsheet-like grid
//
// Clicking "Extract" calls POST /api/admin/onboarding/extract (mock for now)
// and hands the RawMenuExtraction back to the wizard container.
// UI copy: English only per [[feedback-ui-language-english-only]].
import { useState } from 'react'
import SourceTypeToggle from '../components/SourceTypeToggle'
import { extractMenu } from '../api/onboardingClient'
import type {
  ExtractRequest, ManualItemInput, RawMenuExtraction, SourceType,
} from '../types'
import styles from './Step1_SourceUpload.module.css'

interface Props {
  onExtracted: (raw: RawMenuExtraction) => void
}

export default function Step1_SourceUpload({ onExtracted }: Props) {
  const [source, setSource] = useState<SourceType>('loyverse')
  const [apiKey, setApiKey] = useState('')
  const [verifyState, setVerifyState] = useState<'idle' | 'verifying' | 'ok' | 'fail'>('idle')
  const [verifiedStore, setVerifiedStore] = useState<string>('')
  const [url, setUrl] = useState('')
  const [imageFiles, setImageFiles] = useState<File[]>([])
  const [csvFile, setCsvFile] = useState<File | null>(null)
  const [manualRows, setManualRows] = useState<ManualItemInput[]>([
    { name: '', price: 0, category: '' },
    { name: '', price: 0, category: '' },
    { name: '', price: 0, category: '' },
  ])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string>('')

  function buildPayload(): ExtractRequest['payload'] | null {
    switch (source) {
      case 'loyverse':
        if (!apiKey.trim()) return null
        return { api_key: apiKey.trim() }
      case 'url':
        if (!url.trim()) return null
        return { url: url.trim() }
      case 'image':
      case 'pdf':
        if (imageFiles.length === 0) return null
        return { image_paths: imageFiles.flatMap(devMapPdfImage) }
      case 'csv':
        if (!csvFile) return null
        return { file_path: devMapCsv(csvFile) }
      case 'manual': {
        const filled = manualRows.filter((r) => r.name.trim() && r.price > 0)
        if (filled.length === 0) return null
        return { items: filled }
      }
    }
    return null
  }

  const ready = buildPayload() !== null

  function verifyLoyverse() {
    if (!apiKey.trim()) return
    setVerifyState('verifying')
    // Mock: any non-empty key passes. Real impl: GET /api/admin/loyverse/whoami
    setTimeout(() => {
      setVerifyState('ok')
      setVerifiedStore('JM Pizza')
    }, 700)
  }

  async function onExtract() {
    setError('')
    const payload = buildPayload()
    if (!payload) {
      setError('Please complete the input above before continuing.')
      return
    }
    setSubmitting(true)
    try {
      const raw = await extractMenu({ source_type: source, payload })
      onExtracted(raw)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Unknown error'
      setError(`Extract failed: ${msg}`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.wrap}>
      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <span className={styles.stepNum}>1</span>
          <div>
            <h2 className={styles.heading}>Where should we read your menu from?</h2>
            <p className={styles.lead}>
              Choose the easiest path — Loyverse sync is fastest if you already use it.
            </p>
          </div>
        </div>
        <SourceTypeToggle value={source} onChange={(v) => { setSource(v); setError('') }} />
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <span className={styles.stepNum}>2</span>
          <div>
            <h2 className={styles.heading}>Provide your menu</h2>
            <p className={styles.lead}>
              {sourceLead(source)}
            </p>
          </div>
        </div>

        <div className={styles.inputArea}>
          {source === 'loyverse' && (
            <LoyverseInput
              apiKey={apiKey}
              setApiKey={(v) => { setApiKey(v); setVerifyState('idle') }}
              onVerify={verifyLoyverse}
              verifyState={verifyState}
              verifiedStore={verifiedStore}
            />
          )}
          {source === 'url' && <UrlInput url={url} setUrl={setUrl} />}
          {(source === 'image' || source === 'pdf') && (
            <FileDropZone
              multiple
              accept="image/*,application/pdf"
              files={imageFiles}
              onFiles={setImageFiles}
              label="Drop menu photos or PDFs here"
            />
          )}
          {source === 'csv' && (
            <FileDropZone
              multiple={false}
              accept=".csv,text/csv"
              files={csvFile ? [csvFile] : []}
              onFiles={(fs) => setCsvFile(fs[0] ?? null)}
              label="Drop a CSV file here"
            />
          )}
          {source === 'manual' && (
            <ManualGrid rows={manualRows} setRows={setManualRows} />
          )}
        </div>
      </section>

      {error && <div className={styles.error} role="alert">{error}</div>}

      <div className={styles.actions}>
        <p className={styles.actionHint}>
          {ready
            ? "Looks good. We'll extract your items in a moment."
            : 'Complete the section above to continue.'}
        </p>
        <button
          type="button"
          className={styles.primary}
          onClick={onExtract}
          disabled={submitting || !ready}
        >
          {submitting ? 'Extracting menu…' : 'Extract menu →'}
        </button>
      </div>
    </div>
  )
}

// Dev-only mapping for the 2026-05-15 JM Taco validation:
// the browser cannot reach absolute server paths, so when the operator drops
// one of the pre-validated source files we substitute the absolute path the
// backend expects. Real upload endpoint will replace this later.
// (검증 파일 드롭 시 backend가 기대하는 절대경로로 dev 매핑)
const VALIDATION_DIR =
  '/Users/mchangpdx/jm-voice-ai-platform/docs/onboarding-validation/2026-05-15-mexican-validation/sources'

function devMapPdfImage(f: File): string[] {
  if (f.name === 'menu.pdf') {
    return [1, 2, 3].map((i) => `${VALIDATION_DIR}/menu_p${i}.png`)
  }
  if (f.name === 'menu_v2.pdf') {
    return [1, 2, 3, 4, 5, 6].map((i) => `${VALIDATION_DIR}/menu_v2_p${i}.png`)
  }
  // PNG/JPG that's already in the sources dir — pass straight through
  if (/\.(png|jpe?g)$/i.test(f.name)) {
    return [`${VALIDATION_DIR}/${f.name}`]
  }
  // Unknown file: fall back to stub (will fail at backend, but the wizard
  // can surface the error)
  return [`/uploads/${f.name}`]
}

function devMapCsv(f: File): string {
  if (f.name === 'menu.csv') return `${VALIDATION_DIR}/menu.csv`
  return `/uploads/${f.name}`
}

function sourceLead(s: SourceType): string {
  switch (s) {
    case 'loyverse': return 'Paste a Loyverse API access token. We never store it after onboarding.'
    case 'url':      return 'Paste a public URL. We will crawl item names, prices, and categories.'
    case 'image':
    case 'pdf':      return 'Drop one or more menu photos or PDFs. OCR runs automatically.'
    case 'csv':      return 'Upload a spreadsheet with name, price, and category columns.'
    case 'manual':   return 'Type the items by hand. Add as many rows as you need.'
  }
}

/* ── Sub-inputs ──────────────────────────────────────────────────────────── */

function LoyverseInput(props: {
  apiKey: string
  setApiKey: (v: string) => void
  onVerify: () => void
  verifyState: 'idle' | 'verifying' | 'ok' | 'fail'
  verifiedStore: string
}) {
  return (
    <div className={styles.field}>
      <label className={styles.label} htmlFor="loyverse-token">
        Loyverse API access token
      </label>
      <div className={styles.row}>
        <input
          id="loyverse-token"
          type="password"
          className={styles.input}
          placeholder="Paste your token here"
          value={props.apiKey}
          onChange={(e) => props.setApiKey(e.target.value)}
        />
        <button
          type="button"
          className={styles.secondary}
          onClick={props.onVerify}
          disabled={!props.apiKey.trim() || props.verifyState === 'verifying'}
        >
          {props.verifyState === 'verifying' ? 'Verifying…' : 'Verify'}
        </button>
      </div>
      {props.verifyState === 'ok' && (
        <div className={styles.verifyOk}>
          ✓ Connected to <strong>{props.verifiedStore}</strong>
        </div>
      )}
      <p className={styles.help}>
        Find your token in Loyverse Back Office → Settings → API Access tokens.
      </p>
    </div>
  )
}

function UrlInput({ url, setUrl }: { url: string; setUrl: (v: string) => void }) {
  return (
    <div className={styles.field}>
      <label className={styles.label} htmlFor="menu-url">Menu page URL</label>
      <input
        id="menu-url"
        type="url"
        className={styles.input}
        placeholder="https://your-restaurant.com/menu"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
      />
      <p className={styles.help}>
        Public-facing menu page. Works best when prices and item names are in plain text.
      </p>
    </div>
  )
}

function FileDropZone(props: {
  multiple: boolean
  accept: string
  files: File[]
  onFiles: (files: File[]) => void
  label: string
}) {
  const [dragOver, setDragOver] = useState(false)
  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
    const fs = Array.from(e.dataTransfer.files ?? [])
    if (!props.multiple && fs.length > 1) {
      props.onFiles([fs[0]])
    } else {
      props.onFiles(fs)
    }
  }
  function removeAt(idx: number) {
    props.onFiles(props.files.filter((_, i) => i !== idx))
  }
  return (
    <div className={styles.field}>
      <div
        className={`${styles.dropzone} ${dragOver ? styles.dropzoneOver : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
      >
        <div className={styles.dropIcon}>⬆</div>
        <div className={styles.dropLabel}>{props.label}</div>
        <label className={styles.dropBrowse}>
          or browse to upload
          <input
            type="file"
            multiple={props.multiple}
            accept={props.accept}
            onChange={(e) => {
              const fs = Array.from(e.target.files ?? [])
              props.onFiles(fs)
            }}
            hidden
          />
        </label>
        <p className={styles.dropSubhint}>
          {props.multiple ? 'Up to 10 files, 10MB each' : 'One file, up to 5MB'}
        </p>
      </div>
      {props.files.length > 0 && (
        <ul className={styles.fileList}>
          {props.files.map((f, i) => (
            <li key={`${f.name}-${i}`}>
              <span className={styles.fileIcon}>📎</span>
              <span className={styles.fileName}>{f.name}</span>
              <span className={styles.fileSize}>{Math.round(f.size / 1024)} KB</span>
              <button
                type="button"
                className={styles.fileRemove}
                onClick={() => removeAt(i)}
                aria-label={`Remove ${f.name}`}
              >✕</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function ManualGrid(props: {
  rows: ManualItemInput[]
  setRows: (r: ManualItemInput[]) => void
}) {
  function update(i: number, patch: Partial<ManualItemInput>) {
    const next = props.rows.map((r, idx) => idx === i ? { ...r, ...patch } : r)
    props.setRows(next)
  }
  function addRow() {
    props.setRows([...props.rows, { name: '', price: 0, category: '' }])
  }
  function removeRow(i: number) {
    props.setRows(props.rows.filter((_, idx) => idx !== i))
  }
  return (
    <div className={styles.field}>
      <label className={styles.label}>Enter menu items</label>
      <table className={styles.gridTable}>
        <thead>
          <tr>
            <th>Item name</th>
            <th style={{ width: 120 }}>Price (USD)</th>
            <th>Category</th>
            <th style={{ width: 40 }} aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {props.rows.map((r, i) => (
            <tr key={i}>
              <td>
                <input
                  className={styles.cellInput}
                  value={r.name}
                  onChange={(e) => update(i, { name: e.target.value })}
                  placeholder="e.g. Cheese Pizza"
                />
              </td>
              <td>
                <input
                  className={styles.cellInput}
                  type="number"
                  min={0}
                  step="0.01"
                  value={r.price || ''}
                  onChange={(e) => update(i, { price: parseFloat(e.target.value) || 0 })}
                  placeholder="0.00"
                />
              </td>
              <td>
                <input
                  className={styles.cellInput}
                  value={r.category ?? ''}
                  onChange={(e) => update(i, { category: e.target.value })}
                  placeholder="e.g. Pizza"
                />
              </td>
              <td>
                <button
                  type="button"
                  className={styles.delBtn}
                  onClick={() => removeRow(i)}
                  aria-label={`Remove row ${i + 1}`}
                >✕</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button type="button" className={styles.addRowBtn} onClick={addRow}>
        + Add another item
      </button>
    </div>
  )
}
