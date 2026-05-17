// AI Voice Bot management page — persona editor, agent status, knowledge base
// (AI Voice Bot 관리 페이지 — 페르소나 편집, 에이전트 상태, 지식 베이스)
import { useEffect, useState } from 'react'
import api from '../../../core/api'
import Skeleton from '../../../components/Skeleton/Skeleton'
import styles from './AiVoiceBot.module.css'

interface VoiceBotSettings {
  store_name:       string
  system_prompt:    string | null
  temporary_prompt: string | null
}

// Cross-tab + cross-component sync (Overview ↔ AiVoiceBot)
const VOICE_BOT_EVENT = 'voice-bot:updated'
const VOICE_BOT_CHANNEL = 'jm-voice-bot'

interface VoiceBotPayload {
  temporary_prompt: string | null
  system_prompt?: string | null
}

function broadcastVoiceBot(payload: VoiceBotPayload) {
  window.dispatchEvent(
    new CustomEvent<VoiceBotPayload>(VOICE_BOT_EVENT, { detail: payload }),
  )
  try {
    const bc = new BroadcastChannel(VOICE_BOT_CHANNEL)
    bc.postMessage(payload)
    bc.close()
  } catch {
    // BroadcastChannel unsupported — same-tab event still fires.
  }
}

interface AgentStatus {
  model:                string
  voice:                string
  system_prompt_loaded: boolean
  last_call_at:         string | null
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function VoiceIdBadge({ voiceId }: { voiceId: string }) {
  const [provider, name] = voiceId.includes('-') ? voiceId.split('-') : ['', voiceId]
  return (
    <span className={styles.voiceBadge}>
      <span className={styles.voiceProvider}>{provider}</span>
      {name}
    </span>
  )
}

function StatusDot({ active }: { active: boolean }) {
  return <span className={active ? styles.dotGreen : styles.dotGray} />
}

// LCS-based line diff — small (≤ a few hundred lines) so an O(N*M) table is fine.
type DiffLine = { type: 'same' | 'add' | 'del'; line: string }

function computeLineDiff(saved: string, draft: string): DiffLine[] {
  const a = saved.split('\n')
  const b = draft.split('\n')
  const m = a.length, n = b.length
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array<number>(n + 1).fill(0))
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  const out: DiffLine[] = []
  let i = 0, j = 0
  while (i < m && j < n) {
    if (a[i] === b[j])              { out.push({ type: 'same', line: a[i] }); i++; j++ }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push({ type: 'del',  line: a[i] }); i++ }
    else                            { out.push({ type: 'add',  line: b[j] }); j++ }
  }
  while (i < m) out.push({ type: 'del', line: a[i++] })
  while (j < n) out.push({ type: 'add', line: b[j++] })
  return out
}

function InlineDiff({ saved, draft }: { saved: string; draft: string }) {
  const lines = computeLineDiff(saved, draft)
  const adds = lines.filter((l) => l.type === 'add').length
  const dels = lines.filter((l) => l.type === 'del').length
  return (
    <div className={styles.diff}>
      <div className={styles.diffHeader}>
        <span className={styles.diffStatAdd}>+{adds}</span>
        <span className={styles.diffStatDel}>−{dels}</span>
        <span className={styles.diffHeaderHint}>Saved → Draft</span>
      </div>
      <pre className={styles.diffBody}>
        {lines.map((l, i) => (
          <div
            key={i}
            className={
              l.type === 'add' ? styles.diffAdd :
              l.type === 'del' ? styles.diffDel : styles.diffSame
            }
          >
            <span className={styles.diffMark}>
              {l.type === 'add' ? '+' : l.type === 'del' ? '−' : ' '}
            </span>
            <span className={styles.diffLine}>{l.line || ' '}</span>
          </div>
        ))}
      </pre>
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function AiVoiceBot() {
  const [settings,    setSettings   ] = useState<VoiceBotSettings | null>(null)
  const [agentStatus, setAgentStatus] = useState<AgentStatus | null>(null)
  const [loading,     setLoading    ] = useState(true)
  const [agentLoading,setAgentLoading] = useState(true)

  // Prompt draft state
  const [systemDraft,   setSystemDraft  ] = useState('')
  const [tempDraft,     setTempDraft    ] = useState('')
  const [systemSaved,   setSystemSaved  ] = useState('')
  const [tempSaved,     setTempSaved    ] = useState('')

  const [saving,  setSaving ] = useState(false)
  const [toast,   setToast  ] = useState('')
  const [isError, setIsError] = useState(false)
  const [showSystemDiff, setShowSystemDiff] = useState(false)
  const [showTempDiff,   setShowTempDiff  ] = useState(false)

  const systemDirty = systemDraft !== systemSaved
  const tempDirty   = tempDraft   !== tempSaved
  const anyDirty    = systemDirty || tempDirty

  const flash = (msg: string, error = false) => {
    setToast(msg)
    setIsError(error)
    setTimeout(() => setToast(''), 3000)
  }

  // Load voice bot settings
  useEffect(() => {
    api.get('/store/voice-bot')
      .then((r) => {
        const s: VoiceBotSettings = r.data
        setSettings(s)
        setSystemDraft(s.system_prompt ?? '')
        setSystemSaved(s.system_prompt ?? '')
        setTempDraft(s.temporary_prompt ?? '')
        setTempSaved(s.temporary_prompt ?? '')
      })
      .catch(() => flash('Failed to load voice bot settings.', true))
      .finally(() => setLoading(false))
  }, [])

  // Load voice agent status (independent fetch)
  useEffect(() => {
    api.get('/store/voice-bot/agent-status')
      .then((r) => setAgentStatus(r.data))
      .catch(() => setAgentStatus(null))
      .finally(() => setAgentLoading(false))
  }, [])

  // Cross-component + cross-tab sync — Overview saves → mirror here.
  // (Overview에서 daily instructions 저장 시 같은 탭/다른 탭 모두 즉시 반영)
  useEffect(() => {
    const apply = (detail: VoiceBotPayload | null) => {
      if (!detail) return
      if (typeof detail.temporary_prompt === 'string') {
        setTempDraft(detail.temporary_prompt)
        setTempSaved(detail.temporary_prompt)
      }
      if (typeof detail.system_prompt === 'string') {
        setSystemDraft(detail.system_prompt)
        setSystemSaved(detail.system_prompt)
      }
    }
    const sameTab = (e: Event) => apply((e as CustomEvent<VoiceBotPayload>).detail)
    const crossTab = (e: MessageEvent<VoiceBotPayload>) => apply(e.data ?? null)

    window.addEventListener(VOICE_BOT_EVENT, sameTab)
    let bc: BroadcastChannel | null = null
    try {
      bc = new BroadcastChannel(VOICE_BOT_CHANNEL)
      bc.addEventListener('message', crossTab)
    } catch {
      // BroadcastChannel unsupported — same-tab event still fires.
    }
    return () => {
      window.removeEventListener(VOICE_BOT_EVENT, sameTab)
      bc?.removeEventListener('message', crossTab)
      bc?.close()
    }
  }, [])

  const handleSave = async () => {
    if (!anyDirty) return
    setSaving(true)
    try {
      const payload: Record<string, string> = {}
      if (systemDirty) payload.system_prompt    = systemDraft
      if (tempDirty)   payload.temporary_prompt = tempDraft
      const r = await api.patch('/store/voice-bot', payload)
      const updated: VoiceBotSettings = r.data
      setSystemSaved(updated.system_prompt ?? '')
      setTempSaved(updated.temporary_prompt ?? '')
      setSettings(updated)
      broadcastVoiceBot({
        temporary_prompt: updated.temporary_prompt,
        system_prompt:    updated.system_prompt,
      })
      flash('Saved successfully.')
    } catch {
      flash('Save failed. Please try again.', true)
    } finally {
      setSaving(false)
    }
  }

  const handleRevert = () => {
    setSystemDraft(systemSaved)
    setTempDraft(tempSaved)
  }

  if (loading) {
    return (
      <div className={styles.page}>
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className={styles.section}>
            <Skeleton w={220} h={16} />
            <div style={{ height: 14 }} />
            <Skeleton h={i === 1 ? 160 : 100} radius={8} />
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className={styles.page}>

      {/* Toast notification */}
      {toast && (
        <div className={`${styles.toast} ${isError ? styles.toastError : ''}`}>
          {toast}
        </div>
      )}

      {/* Page header */}
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>AI Voice Bot</h1>
        <p className={styles.pageDesc}>
          Manage AI persona and knowledge for{' '}
          <strong>{settings?.store_name}</strong>
        </p>
      </div>

      <div className={styles.grid}>

        {/* ── Left column: Persona Editor ─────────────────────────────────── */}
        <div className={styles.leftCol}>

          {/* Agent Status Card */}
          <div className={styles.section}>
            <div className={styles.sectionHeader}>
              <span className={styles.sectionIcon}>🤖</span>
              <div>
                <h2 className={styles.sectionTitle}>Agent Status</h2>
                <p className={styles.sectionDesc}>OpenAI Realtime voice engine configuration</p>
              </div>
            </div>

            {agentLoading ? (
              <div className={styles.agentCard}>
                <Skeleton w={180} h={14} />
                <div style={{ height: 12 }} />
                <Skeleton h={70} radius={6} />
              </div>
            ) : agentStatus ? (
              <div className={styles.agentCard}>
                <div className={styles.agentRow}>
                  <StatusDot active={true} />
                  <span className={styles.agentName}>{agentStatus.model}</span>
                  <span className={styles.agentBadge}>OpenAI Realtime</span>
                </div>
                <div className={styles.agentMeta}>
                  <div className={styles.metaItem}>
                    <span className={styles.metaLabel}>Voice</span>
                    <VoiceIdBadge voiceId={agentStatus.voice} />
                  </div>
                  <div className={styles.metaItem}>
                    <span className={styles.metaLabel}>System prompt</span>
                    <span className={agentStatus.system_prompt_loaded ? styles.wsConnected : styles.wsNotSet}>
                      {agentStatus.system_prompt_loaded ? '✓ Loaded' : '⚠ Not configured'}
                    </span>
                  </div>
                  <div className={styles.metaItem}>
                    <span className={styles.metaLabel}>Last call</span>
                    <code className={styles.metaCode}>
                      {agentStatus.last_call_at ? new Date(agentStatus.last_call_at).toLocaleString() : '—'}
                    </code>
                  </div>
                </div>
              </div>
            ) : (
              <div className={styles.agentEmpty}>
                <p>No voice agent configured for this store.</p>
                <p className={styles.agentEmptyHint}>Contact your agency to assign an agent.</p>
              </div>
            )}
          </div>

          {/* Core AI Persona */}
          <div className={styles.section}>
            <div className={styles.sectionHeader}>
              <span className={styles.sectionIcon}>🔒</span>
              <div className={styles.sectionHeaderText}>
                <h2 className={styles.sectionTitle}>
                  Core AI Persona
                  <span className={styles.badgeEssential}>Essential</span>
                </h2>
                <p className={styles.sectionDesc}>
                  The foundational AI identity. Edit with care — affects every call.
                </p>
              </div>
              {systemDirty && (
                <button
                  type="button"
                  className={styles.diffToggle}
                  onClick={() => setShowSystemDiff((v) => !v)}
                >
                  {showSystemDiff ? 'Hide diff' : 'Show diff'}
                </button>
              )}
            </div>
            <textarea
              className={styles.textarea}
              value={systemDraft}
              onChange={(e) => setSystemDraft(e.target.value)}
              rows={8}
              placeholder="e.g. You are Aria, the friendly AI voice assistant for JM Cafe…"
            />
            <p className={styles.charCount}>{systemDraft.length.toLocaleString()} characters</p>
            {systemDirty && showSystemDiff && (
              <InlineDiff saved={systemSaved} draft={systemDraft} />
            )}
          </div>

          {/* Daily Instructions */}
          <div className={styles.section}>
            <div className={styles.sectionHeader}>
              <span className={styles.sectionIcon}>⚡</span>
              <div className={styles.sectionHeaderText}>
                <h2 className={styles.sectionTitle}>
                  Daily Instructions
                  <span className={styles.badgeTemp}>Temporary</span>
                </h2>
                <p className={styles.sectionDesc}>
                  Today's specials, sold-out items, or event notes. Highest priority during live calls.
                </p>
              </div>
              {tempDirty && (
                <button
                  type="button"
                  className={styles.diffToggle}
                  onClick={() => setShowTempDiff((v) => !v)}
                >
                  {showTempDiff ? 'Hide diff' : 'Show diff'}
                </button>
              )}
            </div>
            <textarea
              className={`${styles.textarea} ${styles.textareaAmber}`}
              value={tempDraft}
              onChange={(e) => setTempDraft(e.target.value)}
              rows={4}
              placeholder="e.g. Matcha latte is sold out today. Happy hour 50% off drinks before 6 PM."
            />
            <p className={styles.charCount}>{tempDraft.length.toLocaleString()} characters</p>
            {tempDirty && showTempDiff && (
              <InlineDiff saved={tempSaved} draft={tempDraft} />
            )}
          </div>

          {/* Save / Revert buttons */}
          <div className={styles.actions}>
            <button
              className={styles.btnSave}
              onClick={handleSave}
              disabled={saving || !anyDirty}
            >
              {saving ? 'Saving…' : '💾 Save Changes'}
            </button>
            <button
              className={styles.btnRevert}
              onClick={handleRevert}
              disabled={saving || !anyDirty}
            >
              ↩ Revert
            </button>
            {anyDirty && <span className={styles.unsaved}>Unsaved changes</span>}
          </div>
        </div>

        {/* ── Right column: Knowledge Base (read from DB, edit in Settings later) ── */}
        <div className={styles.rightCol}>

          {/* How It Works */}
          <div className={styles.section}>
            <div className={styles.sectionHeader}>
              <span className={styles.sectionIcon}>📡</span>
              <div>
                <h2 className={styles.sectionTitle}>How It Works</h2>
                <p className={styles.sectionDesc}>OpenAI Realtime voice engine flow</p>
              </div>
            </div>
            <div className={styles.flowList}>
              {[
                { step: '1', label: 'Customer calls your phone number (Twilio Media Streams)' },
                { step: '2', label: 'Server VAD detects speech (1200ms silence threshold)' },
                { step: '3', label: 'OpenAI Realtime processes audio with your persona (STT + LLM + TTS native)' },
                { step: '4', label: 'Voice response streamed back to caller in real time' },
                { step: '5', label: 'Call log + summary + receipt saved automatically' },
              ].map(({ step, label }) => (
                <div key={step} className={styles.flowItem}>
                  <span className={styles.flowStep}>{step}</span>
                  <span className={styles.flowLabel}>{label}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Prompt Priority Guide */}
          <div className={styles.section}>
            <div className={styles.sectionHeader}>
              <span className={styles.sectionIcon}>📋</span>
              <div>
                <h2 className={styles.sectionTitle}>Prompt Priority</h2>
                <p className={styles.sectionDesc}>How the AI uses your instructions</p>
              </div>
            </div>
            <div className={styles.priorityList}>
              <div className={styles.priorityItem}>
                <div className={`${styles.priorityBar} ${styles.priorityHigh}`} />
                <div>
                  <p className={styles.priorityTitle}>Daily Instructions (Highest)</p>
                  <p className={styles.priorityDesc}>Today's overrides — injected last, takes top priority</p>
                </div>
              </div>
              <div className={styles.priorityItem}>
                <div className={`${styles.priorityBar} ${styles.priorityMed}`} />
                <div>
                  <p className={styles.priorityTitle}>Core AI Persona</p>
                  <p className={styles.priorityDesc}>Foundational identity, tone, and capabilities</p>
                </div>
              </div>
              <div className={styles.priorityItem}>
                <div className={`${styles.priorityBar} ${styles.priorityLow}`} />
                <div>
                  <p className={styles.priorityTitle}>Business Hours + Knowledge</p>
                  <p className={styles.priorityDesc}>Static store info — edit in Store Settings</p>
                </div>
              </div>
            </div>
          </div>

          {/* Quick Tips */}
          <div className={styles.section}>
            <div className={styles.sectionHeader}>
              <span className={styles.sectionIcon}>💡</span>
              <div>
                <h2 className={styles.sectionTitle}>Quick Tips</h2>
              </div>
            </div>
            <ul className={styles.tipList}>
              <li>Keep the Core Persona under 500 characters for best performance</li>
              <li>Update Daily Instructions each morning for specials or events</li>
              <li>Clear Daily Instructions at end of day to avoid stale info</li>
              <li>Test your agent by calling the assigned phone number</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  )
}
