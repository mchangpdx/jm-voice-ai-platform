// Step 1 — Source Upload: pick a source type and provide input.
// (Step 1 — 소스 업로드: 5개 source type 중 선택 후 입력)
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
  const [verifyState, setVerifyState] = useState<'idle' | 'ok' | 'fail'>('idle')
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
        // Backend will accept presigned-S3 paths in real impl; mock ignores.
        return { image_paths: imageFiles.map((f) => `/uploads/${f.name}`) }
      case 'csv':
        if (!csvFile) return null
        return { file_path: `/uploads/${csvFile.name}` }
      case 'manual': {
        const filled = manualRows.filter((r) => r.name.trim() && r.price > 0)
        if (filled.length === 0) return null
        return { items: filled }
      }
    }
    return null
  }

  async function verifyLoyverse() {
    if (!apiKey.trim()) return
    setVerifyState('idle')
    // Mock: any non-empty key passes. Real impl: GET /api/admin/loyverse/whoami
    setTimeout(() => {
      setVerifyState('ok')
      setVerifiedStore('JM Pizza (mock verified)')
    }, 700)
  }

  async function onExtract() {
    setError('')
    const payload = buildPayload()
    if (!payload) {
      setError('Please provide the required input above (입력값을 채워주세요)')
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
      <h2 className={styles.heading}>
        Choose a menu source <span className={styles.headingKo}>(메뉴 소스 선택)</span>
      </h2>
      <SourceTypeToggle value={source} onChange={(v) => { setSource(v); setError('') }} />

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
            label="Drop menu photos or PDFs here (메뉴 사진/PDF 끌어다 놓기)"
          />
        )}
        {source === 'csv' && (
          <FileDropZone
            multiple={false}
            accept=".csv,text/csv"
            files={csvFile ? [csvFile] : []}
            onFiles={(fs) => setCsvFile(fs[0] ?? null)}
            label="Drop a CSV file here (CSV 파일 끌어다 놓기)"
          />
        )}
        {source === 'manual' && (
          <ManualGrid rows={manualRows} setRows={setManualRows} />
        )}
      </div>

      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.actions}>
        <button
          type="button"
          className={styles.primary}
          onClick={onExtract}
          disabled={submitting}
        >
          {submitting
            ? 'Extracting… (추출 중)'
            : 'Extract menu items → (메뉴 추출)'}
        </button>
      </div>
    </div>
  )
}

/* ── Sub-inputs ──────────────────────────────────────────────────────────── */

function LoyverseInput(props: {
  apiKey: string
  setApiKey: (v: string) => void
  onVerify: () => void
  verifyState: 'idle' | 'ok' | 'fail'
  verifiedStore: string
}) {
  return (
    <div className={styles.field}>
      <label className={styles.label}>
        Loyverse API token (Loyverse API 토큰)
      </label>
      <div className={styles.row}>
        <input
          type="password"
          className={styles.input}
          placeholder="Paste your Loyverse token here"
          value={props.apiKey}
          onChange={(e) => props.setApiKey(e.target.value)}
        />
        <button
          type="button"
          className={styles.secondary}
          onClick={props.onVerify}
          disabled={!props.apiKey.trim()}
        >
          Verify (확인)
        </button>
      </div>
      {props.verifyState === 'ok' && (
        <div className={styles.verifyOk}>
          ✓ Connected — {props.verifiedStore}
        </div>
      )}
      <p className={styles.help}>
        Find your token in Loyverse Back Office → Settings → API Access tokens.
        <br />
        <span className={styles.helpKo}>
          Loyverse 백오피스 → 설정 → API 액세스 토큰에서 생성
        </span>
      </p>
    </div>
  )
}

function UrlInput({ url, setUrl }: { url: string; setUrl: (v: string) => void }) {
  return (
    <div className={styles.field}>
      <label className={styles.label}>Menu page URL (메뉴 페이지 URL)</label>
      <input
        type="url"
        className={styles.input}
        placeholder="https://your-restaurant.com/menu"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
      />
      <p className={styles.help}>
        Public-facing menu URL. We crawl prices, names and categories.
        <br />
        <span className={styles.helpKo}>공개된 메뉴 페이지 — 자동 크롤링 후 추출</span>
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
  return (
    <div className={styles.field}>
      <div
        className={`${styles.dropzone} ${dragOver ? styles.dropzoneOver : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
      >
        <div className={styles.dropIcon}>⬇</div>
        <div className={styles.dropLabel}>{props.label}</div>
        <label className={styles.dropBrowse}>
          or browse files (또는 파일 선택)
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
      </div>
      {props.files.length > 0 && (
        <ul className={styles.fileList}>
          {props.files.map((f) => (
            <li key={f.name}>📎 {f.name} <span className={styles.fileSize}>({Math.round(f.size / 1024)} KB)</span></li>
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
      <label className={styles.label}>Enter menu items (메뉴 직접 입력)</label>
      <table className={styles.gridTable}>
        <thead>
          <tr>
            <th>Name (이름)</th>
            <th style={{ width: 120 }}>Price ($)</th>
            <th>Category (카테고리)</th>
            <th style={{ width: 40 }} />
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
        + Add row (행 추가)
      </button>
    </div>
  )
}
