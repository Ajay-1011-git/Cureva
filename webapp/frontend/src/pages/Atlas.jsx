import { useCallback, useEffect, useRef, useState } from 'react'
import AvatarCanvas from '../avatar/AvatarCanvas.jsx'
import FindingGraphPanel from '../components/FindingGraphPanel.jsx'
import MicButton from '../components/MicButton.jsx'
import SubjectPicker from '../components/SubjectPicker.jsx'
import PageHero from '../components/PageHero.jsx'
import Icon from '../components/Icon.jsx'
import { useReveal, useMagnetic } from '../lib/motion.js'

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
  // She leans in once the conversation has actually started, and stays
  // leaning for the rest of it — reset when the subject changes, since
  // that is a new conversation with a different person.
  const [engaged, setEngaged] = useState(false)
  const [subjects, setSubjects] = useState([])
  const [usubjid, setUsubjid] = useState(
    import.meta.env.VITE_DEMO_SUBJECT || '042-S07-001')
  const audioRef = useRef(null)
  const [audioEl, setAudioEl] = useState(null)
  const logRef = useRef(null)

  const bodyRef = useReveal([])
  const sendRef = useMagnetic({ strength: 4 })

  useEffect(() => {
    fetch(`${API_BASE}/api/atlas/subjects`)
      .then((r) => r.json())
      .then(setSubjects)
      .catch((e) => console.warn('subject list unavailable', e))
  }, [])

  useEffect(() => {
    const el = new Audio()
    el.crossOrigin = 'anonymous'
    audioRef.current = el
    setAudioEl(el)
  }, [])

  // Keep the newest turn in view. Without this the transcript silently grows
  // downward and the reply you are waiting for lands off screen.
  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const sendTurn = useCallback(async (payload) => {
    setBusy(true)
    setEngaged(true)
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
        ?? (data.transcript || '(nothing heard)')
      setMessages((m) => [...m,
        { role: 'patient', text: heard, spoken: !payload.text },
        { role: 'avatar', text: data.reply_text, extracted: data.extracted,
          redFlags: data.red_flags || [] }])
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

  // A conversation belongs to one subject. Switching person clears the log —
  // leaving another patient's words on screen under a new name would be
  // misleading in exactly the way clinical records must never be.
  useEffect(() => { setMessages([]); setGesture('idle'); setEngaged(false) }, [usubjid])

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
    <div className="page">
      <PageHero
        eyebrow="Act 1 · Atlas"
        eyebrowIcon="graph"
        title="The whole study, and the voice inside it."
        sub="Speak with an enrolled participant. What they say is written into the record and shows up in the finding graph beside it — in the same turn, with the quote still attached."
      />

      <div className="console">
        <div className="console-card">
          <span className="console-label">
            <Icon name="user" size={14} />
            Speaking with
          </span>
          <SubjectPicker subjects={subjects} value={usubjid}
                         onChange={setUsubjid} disabled={busy} />
          <span className="console-spacer" />
          <span className="console-hint">
            the enrolled participant this conversation adds records to
          </span>
        </div>
      </div>

      <div className="page-body" ref={bodyRef}>
        <div className="l-workspace">
          {degraded && (
            <div className="notice notice-warn" style={{ marginBottom: 22 }} data-reveal>
              <Icon name="alert" size={16} />
              <span>
                <strong>Voice service degraded.</strong> Running text-only with canned
                replies. Everything is still being noted — it is just not spoken aloud.
              </span>
            </div>
          )}

          <div className="atlas-grid">
            <section className="atlas-col">
              <div className="card avatar-card" data-reveal data-reveal-group="left">
                <AvatarCanvas gesture={gesture} audioEl={audioEl} engaged={engaged} />
              </div>

              <div className="card chat-card" data-reveal data-reveal-group="left">
                <div className="chat-log u-scroll" ref={logRef}>
                  {messages.length === 0 ? (
                    <div className="chat-empty">
                      <Icon name="mic" size={26} strokeWidth={1.4} />
                      Ask how they have been feeling, or say a symptom out loud.
                      Every term is written back with the sentence it came from.
                    </div>
                  ) : messages.map((m, i) => (
                    <div key={i} className={`chat-msg is-${m.role}`}>
                      <span className="chat-role">
                        {m.role === 'patient' && m.spoken && <Icon name="mic" size={11} />}
                        {m.role === 'patient' ? 'patient' : m.role === 'avatar' ? 'atlas' : 'system'}
                      </span>
                      <div className="chat-bubble">{m.text}</div>

                      {m.redFlags?.length > 0 && (
                        <div className="chat-chips">
                          {m.redFlags.map((f, j) => (
                            <span key={j} className="chip chip-flag" title={f.term}>
                              <Icon name="flag" size={11} /> {f.reason}
                            </span>
                          ))}
                        </div>
                      )}

                      {m.extracted?.length > 0 && (
                        <div className="chat-chips">
                          {m.extracted.map((e, j) => (
                            <span key={j}
                                  className={`chip ${e.pro_type === 'CONMED_MENTION' ? 'chip-conmed' : 'chip-symptom'}`}>
                              <Icon name={e.pro_type === 'CONMED_MENTION' ? 'document' : 'pulse'} size={11} />
                              {e.term}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>

                {micNotice && (
                  <div className="composer-notice">
                    <Icon name="alert" size={13} /> {micNotice}
                  </div>
                )}

                <div className="composer">
                  <MicButton onClip={handleClip} disabled={busy}
                             onUnavailable={setMicNotice} />
                  <input
                    className="input"
                    type="text"
                    placeholder="Speak, or type a symptom or medication…"
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                    disabled={busy}
                  />
                  <button ref={sendRef}
                          className="btn btn-primary composer-send"
                          onClick={handleSend}
                          disabled={busy || !text.trim()}
                          aria-label="Send"
                          data-testid="send-button">
                    {busy
                      ? <span className="ask-thinking"><i /><i /><i /></span>
                      : <Icon name="send" size={16} />}
                  </button>
                </div>
              </div>
            </section>

            <section className="atlas-col" data-reveal data-reveal-group="right">
              <FindingGraphPanel apiBase={API_BASE} refreshKey={graphVersion}
                                 subject={usubjid} onSelectSubject={setUsubjid} />
            </section>
          </div>
        </div>
      </div>
    </div>
  )
}
