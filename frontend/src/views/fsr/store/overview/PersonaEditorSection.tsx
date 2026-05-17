// AI Persona Editor — core persona (read-only) + Daily Instructions (editable).
// Cross-tab + cross-component sync via BroadcastChannel + window event.
// (AI 페르소나 편집기 — Daily Instructions BroadcastChannel + window event 동기화)
import { useEffect, useState } from 'react'
import api from '../../../../core/api'
import styles from '../Overview.module.css'

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

export default function PersonaEditorSection({ storeName }: { storeName: string | null }) {
  const [dailyInstructions, setDailyInstructions] = useState('')
  const [savedInstructions, setSavedInstructions] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')

  useEffect(() => {
    api
      .get('/store/voice-bot')
      .then((r) => {
        const value = (r.data?.temporary_prompt ?? '') as string
        setDailyInstructions(value)
        setSavedInstructions(value)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    const apply = (detail: VoiceBotPayload | null) => {
      if (!detail) return
      const value = detail.temporary_prompt ?? ''
      setDailyInstructions(value)
      setSavedInstructions(value)
    }
    const sameTab = (e: Event) =>
      apply((e as CustomEvent<VoiceBotPayload>).detail)
    const crossTab = (e: MessageEvent<VoiceBotPayload>) => apply(e.data ?? null)

    window.addEventListener(VOICE_BOT_EVENT, sameTab)
    let bc: BroadcastChannel | null = null
    try {
      bc = new BroadcastChannel(VOICE_BOT_CHANNEL)
      bc.addEventListener('message', crossTab)
    } catch {
      // BroadcastChannel unsupported — fall back to same-tab only.
    }
    return () => {
      window.removeEventListener(VOICE_BOT_EVENT, sameTab)
      bc?.removeEventListener('message', crossTab)
      bc?.close()
    }
  }, [])

  const handleSave = async () => {
    if (saving) return
    if (dailyInstructions === savedInstructions) return
    setSaving(true)
    setSaveError('')
    try {
      const r = await api.patch('/store/voice-bot', {
        temporary_prompt: dailyInstructions,
      })
      const updated = (r.data?.temporary_prompt ?? '') as string
      setSavedInstructions(updated)
      setDailyInstructions(updated)
      broadcastVoiceBot({ temporary_prompt: updated })
    } catch {
      setSaveError('Save failed. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={styles.personaPanel}>
      <div className={styles.panelHeader}>
        <span className={styles.panelIcon}>🤖</span>
        <div>
          <div className={styles.panelTitle}>AI Persona Editor</div>
          <div className={styles.panelDesc}>
            Manage your AI voice assistant's core identity and today's daily instructions.
          </div>
        </div>
      </div>

      <div className={styles.personaSection}>
        <div className={styles.personaLabelRow}>
          <span className={styles.personaLabel}>Core AI Persona</span>
          <span className={styles.essentialBadge}>Essential</span>
        </div>
        <p className={styles.personaNote}>
          Set by your agency. Defines the AI's core identity and cannot be changed from this view.
        </p>
        <textarea
          className={styles.personaTextarea}
          readOnly
          rows={5}
          value={`You are Sophia, the AI receptionist for "${storeName ?? 'your store'}".
Your primary goal is to assist customers with food/drink orders and table reservations politely and efficiently.
Always speak in a highly cheerful, upbeat, energetic, and welcoming tone. Smile with your voice!`}
        />
      </div>

      <div className={styles.divider}>DAILY OVERRIDE</div>

      <div className={styles.personaSection}>
        <div className={styles.personaLabelRow}>
          <span className={styles.personaLabel}>Daily Instructions</span>
          <span className={styles.tempBadge}>Temporary</span>
        </div>
        <p className={styles.personaNote}>
          Today's specials, sold-out items, or event notes. Highest priority during live calls.
        </p>
        <textarea
          className={styles.personaTextarea}
          rows={3}
          value={dailyInstructions}
          onChange={(e) => setDailyInstructions(e.target.value)}
          placeholder="e.g. Early summer Special 30% off cold drinks!"
        />
        <div className={styles.charCount}>{dailyInstructions.length} characters</div>
        {saveError && (
          <div style={{ color: '#dc2626', fontSize: 12, marginTop: 4 }}>{saveError}</div>
        )}
        <div className={styles.personaBtns}>
          <button
            className={styles.saveBtn}
            onClick={handleSave}
            disabled={saving || dailyInstructions === savedInstructions}
          >
            💾 {saving ? 'Saving...' : 'Save Changes'}
          </button>
          <button
            className={styles.revertBtn}
            onClick={() => setDailyInstructions(savedInstructions)}
            disabled={saving || dailyInstructions === savedInstructions}
          >
            ↺ Revert
          </button>
        </div>
      </div>
    </div>
  )
}
