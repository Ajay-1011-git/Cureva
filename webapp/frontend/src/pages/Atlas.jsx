import { useCallback, useEffect, useRef, useState } from 'react'
import gsap from 'gsap'
import AvatarCanvas from '../avatar/AvatarCanvas.jsx'
import FindingGraphPanel from '../components/FindingGraphPanel.jsx'
import MicButton from '../components/MicButton.jsx'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

/**
 * Page 1 (T1.32): avatar canvas + live finding graph, split view.
 *
 * Turn-based (TRD §5: no WebSocket) — type or record, POST /avatar-turn,
 * play the reply, then re-poll /finding-graph so the panel reflects anything
 * the turn's PRO write mapped into a new finding.
 */
export default function Atlas() {
  const [gesture, setGesture] = useState('idle')
  const [text, setText] = useState('')
  const [messages, setMessages] = useState([])
  const [busy, setBusy] = useState(false)
  const [degraded, setDegraded] = useState(false)
  // Which subject the conversation is "about". Overridable in the UI and via
  // VITE_DEMO_SUBJECT so nothing is pinned to one practice-study id — the
  // default is just a subject that has a real finding to show, which makes
  // the demo's cause-and-effect visible without hunting for one live.
  const [micNotice, setMicNotice] = useState(null)
  const [usubjid, setUsubjid] = useState(
    import.meta.env.VITE_DEMO_SUBJECT || '042-S07-001')
  const audioRef = useRef(null)
  const [audioEl, setAudioEl] = useState(null)

  useEffect(() => {
    const el = new Audio()
    el.crossOrigin = 'anonymous'
    audioRef.current = el
    setAudioEl(el)
  }, [])

  const sendTurn = useCallback(async (payload) => {
    setBusy(true)
    setGesture('listening')
    try {
      const resp = await fetch(`${API_BASE}/api/atlas/avatar-turn`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...payload, usubjid }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()

      // For a spoken turn, show what was actually transcribed — not a generic
      // "(spoken)" placeholder. If the transcription misheard you, that has to
      // be visible or the conversation is impossible to debug live.
      const heard = payload.text
        ?? (data.transcript ? `🎤 ${data.transcript}` : '🎤 (nothing heard)')
      setMessages((m) => [...m, { role: 'patient', text: heard },
        { role: 'avatar', text: data.reply_text, extracted: data.extracted }])
      setGesture(data.gesture)
      setDegraded(Boolean(data.degraded))

      if (data.reply_audio_b64 && audioRef.current) {
        const bytes = atob(data.reply_audio_b64)
        const buf = new Uint8Array(bytes.length)
        for (let i = 0; i < bytes.length; i++) buf[i] = bytes.charCodeAt(i)
        const blob = new Blob([buf], { type: 'audio/wav' })
        audioRef.current.src = URL.createObjectURL(blob)
        audioRef.current.play().catch(() => {})
      }
      return data
    } catch (err) {
      console.error('avatar-turn failed', err)
      setDegraded(true)
      setGesture('idle')
      setMessages((m) => [...m, { role: 'system', text: 'Could not reach the avatar service.' }])
    } finally {
      setBusy(false)
    }
  }, [usubjid])

  const [graphVersion, setGraphVersion] = useState(0)

  const handleSend = async () => {
    if (!text.trim() || busy) return
    const spoken = text
    setText('')
    await sendTurn({ text: spoken })
    setGraphVersion((v) => v + 1)      // trigger a finding-graph re-poll
  }

  const handleClip = async (audio_b64, audio_mime) => {
    if (busy) return
    await sendTurn({ audio_b64, audio_mime })
    setGraphVersion((v) => v + 1)
  }

  return (
    <div className="atlas-page">
      <h1>Atlas</h1>
      {degraded && (
        <div className="degraded-banner">
          Voice service degraded — running in text-only / canned-reply mode. Replies are still being noted, just not spoken.
        </div>
      )}
      <div className="atlas-subject-row">
        <label htmlFor="usubjid-input">Subject</label>
        <input id="usubjid-input" type="text" value={usubjid}
          onChange={(e) => setUsubjid(e.target.value)} data-testid="usubjid-input" />
      </div>
      <div className="atlas-split">
        <section className="atlas-avatar-col">
          <AvatarCanvas gesture={gesture} audioEl={audioEl} />
          <div className="chat-log">
            {messages.map((m, i) => (
              <div key={i} className={`chat-msg chat-${m.role}`}>
                <span className="chat-role">{m.role}</span> {m.text}
              </div>
            ))}
          </div>
          {micNotice && <div className="mic-notice">{micNotice}</div>}
          <div className="chat-input-row">
            <MicButton onClip={handleClip} disabled={busy}
                       onUnavailable={setMicNotice} />
            <input
              type="text"
              placeholder="Speak, or type a symptom or medication…"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSend()}
              disabled={busy}
            />
            <button onClick={handleSend} disabled={busy || !text.trim()}
                    data-testid="send-button">
              {busy ? '…' : 'Send'}
            </button>
          </div>
        </section>
        <section className="atlas-graph-col">
          <FindingGraphPanel apiBase={API_BASE} refreshKey={graphVersion} />
        </section>
      </div>
    </div>
  )
}
