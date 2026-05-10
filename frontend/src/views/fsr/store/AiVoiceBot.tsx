// AI Voice Bot management page — persona editor, agent status, knowledge base
// (AI Voice Bot 관리 페이지 — 페르소나 편집, 에이전트 상태, 지식 베이스)
import { useEffect, useState } from 'react'
import api from '../../../core/api'
import styles from './AiVoiceBot.module.css'

interface VoiceBotSettings {
  store_name:       string
  retell_agent_id:  string | null
  system_prompt:    string | null
  temporary_prompt: string | null
}

interface AgentStatus {
  agent_id:          string
  agent_name:        string
  voice_id:          string
  llm_websocket_url: string | null
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
    return <div className={styles.loading}>Loading AI Voice Bot settings…</div>
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
              <p className={styles.agentLoading}>Loading voice agent…</p>
            ) : agentStatus ? (
              <div className={styles.agentCard}>
                <div className={styles.agentRow}>
                  <StatusDot active={true} />
                  <span className={styles.agentName}>{agentStatus.agent_name}</span>
                  <span className={styles.agentBadge}>OpenAI Realtime</span>
                </div>
                <div className={styles.agentMeta}>
                  <div className={styles.metaItem}>
                    <span className={styles.metaLabel}>Voice</span>
                    <VoiceIdBadge voiceId={agentStatus.voice_id} />
                  </div>
                  <div className={styles.metaItem}>
                    <span className={styles.metaLabel}>Agent ID</span>
                    <code className={styles.metaCode}>
                      {agentStatus.agent_id.slice(0, 24)}…
                    </code>
                  </div>
                  <div className={styles.metaItem}>
                    <span className={styles.metaLabel}>WebSocket</span>
                    <span className={agentStatus.llm_websocket_url ? styles.wsConnected : styles.wsNotSet}>
                      {agentStatus.llm_websocket_url ? '✓ Configured' : '⚠ Not configured'}
                    </span>
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
              <div>
                <h2 className={styles.sectionTitle}>
                  Core AI Persona
                  <span className={styles.badgeEssential}>Essential</span>
                </h2>
                <p className={styles.sectionDesc}>
                  The foundational AI identity. Edit with care — affects every call.
                </p>
              </div>
            </div>
            <textarea
              className={styles.textarea}
              value={systemDraft}
              onChange={(e) => setSystemDraft(e.target.value)}
              rows={8}
              placeholder="e.g. You are Aria, the friendly AI voice assistant for JM Cafe…"
            />
            <p className={styles.charCount}>{systemDraft.length.toLocaleString()} characters</p>
          </div>

          {/* Daily Instructions */}
          <div className={styles.section}>
            <div className={styles.sectionHeader}>
              <span className={styles.sectionIcon}>⚡</span>
              <div>
                <h2 className={styles.sectionTitle}>
                  Daily Instructions
                  <span className={styles.badgeTemp}>Temporary</span>
                </h2>
                <p className={styles.sectionDesc}>
                  Today's specials, sold-out items, or event notes. Highest priority during live calls.
                </p>
              </div>
            </div>
            <textarea
              className={`${styles.textarea} ${styles.textareaAmber}`}
              value={tempDraft}
              onChange={(e) => setTempDraft(e.target.value)}
              rows={4}
              placeholder="e.g. Matcha latte is sold out today. Happy hour 50% off drinks before 6 PM."
            />
            <p className={styles.charCount}>{tempDraft.length.toLocaleString()} characters</p>
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
