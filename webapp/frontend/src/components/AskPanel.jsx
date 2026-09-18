import { useCallback, useEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { gsap, reducedMotion } from '../lib/motion.js'

// Same convention the rest of the app uses (Atlas.jsx): the backend's origin
// comes from the environment, because there is no dev-server proxy. A bare
// "/api/..." would resolve against vite's own origin and 404.
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

const EXAMPLES = [
  "Which subjects meet Hy's law criteria?",
  'How many subjects at site S11 discontinued due to an adverse event?',
  'Is any subject enrolled at more than one site?',
]

/**
 * A floating question box, bottom-right. Collapsed it is an obsidian pill —
 * the same shape as every other call to action; on hover it grows into a
 * white card and the page behind it recedes.
 *
 * Two behaviours that hover alone would get wrong:
 *
 *  - Once you have typed or asked something, the panel stays open when the
 *    pointer leaves. A panel that collapsed mid-sentence, or that threw away
 *    an answer because the mouse drifted, would be unusable for the one thing
 *    it exists to do. Escape or a click outside closes it.
 *  - The scrim blurs the page rather than the app blurring itself, so the
 *    answer sits on an unblurred surface while everything behind recedes —
 *    and no fixed-position child of the app is broken by a filter.
 *
 * Questions go to /api/atlas/ask with empty params, so the backend resolves
 * the sentence through Atlas's own deterministic text path. No model is
 * involved and none is needed.
 */
export default function AskPanel() {
  const [open, setOpen] = useState(false)
  const [pinned, setPinned] = useState(false)   // survives the pointer leaving
  const [text, setText] = useState('')
  const [answer, setAnswer] = useState(null)
  const [busy, setBusy] = useState(false)

  const rootRef = useRef(null)
  const cardRef = useRef(null)
  const scrimRef = useRef(null)
  const inputRef = useRef(null)

  const expanded = open || pinned

  // Grow/shrink the card, and fade the scrim over the page behind it.
  useEffect(() => {
    const card = cardRef.current
    const scrim = scrimRef.current
    if (!card) return
    const instant = reducedMotion() ? 0 : undefined

    gsap.to(card, {
      width: expanded ? 440 : 156,
      height: expanded ? 'auto' : 46,
      duration: instant ?? 0.46,
      ease: expanded ? 'power3.out' : 'power2.inOut',
    })
    if (scrim) {
      gsap.to(scrim, { opacity: expanded ? 1 : 0, duration: instant ?? 0.42, ease: 'power2.out' })
    }
  }, [expanded])

  // Focus the input once it is actually visible, not while it is 156px wide.
  useEffect(() => {
    if (expanded) {
      const t = setTimeout(() => inputRef.current?.focus(), 190)
      return () => clearTimeout(t)
    }
  }, [expanded])

  // Escape closes; a click outside closes. Both only matter while pinned,
  // since an unpinned panel closes itself when the pointer leaves.
  useEffect(() => {
    if (!pinned) return
    const close = () => { setPinned(false); setOpen(false) }
    const onKey = (e) => { if (e.key === 'Escape') close() }
    const onClick = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) close()
      // A click on the scrim is inside .ask-root but outside the card.
      else if (cardRef.current && !cardRef.current.contains(e.target)) close()
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('mousedown', onClick)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('mousedown', onClick)
    }
  }, [pinned])

  const ask = useCallback(async () => {
    const question = text.trim()
    if (!question || busy) return
    setBusy(true)
    setPinned(true)
    setAnswer(null)
    try {
      const res = await fetch(`${API_BASE}/api/atlas/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // Empty params on purpose: the sentence is the question, and Atlas
        // resolves it deterministically on the server.
        body: JSON.stringify({ id: 'ui', kind: 'finding', text: question, params: {} }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setAnswer(await res.json())
    } catch (err) {
      setAnswer({ _error: String(err.message || err) })
    } finally {
      setBusy(false)
    }
  }, [text, busy])

  const renderAnswer = () => {
    if (busy) {
      return (
        <div className="ask-status">
          <span className="ask-thinking"><i /><i /><i /></span> reading the graph…
        </div>
      )
    }
    if (!answer) return null
    if (answer._error) {
      return (
        <div className="ask-status ask-status-err">
          could not reach the backend — {answer._error}
        </div>
      )
    }

    const value = answer.answer
    const unresolved = value === null || answer.confidence === 0

    return (
      <div className="ask-answer">
        {unresolved ? (
          <div className="ask-status ask-status-err">{answer.text}</div>
        ) : (
          <>
            <div className="ask-value">
              {Array.isArray(value)
                ? (value.length ? value.join(', ') : 'Nothing — and that is the answer.')
                : String(value)}
            </div>
            <div className="ask-meta">
              {answer.evidence?.length || 0} evidence record(s) · confidence {answer.confidence}
            </div>
            {answer.evidence?.length > 0 && (
              <ul className="ask-evidence">
                {answer.evidence.slice(0, 6).map((e, i) => (
                  <li key={i}>
                    {e.document
                      ? `${e.document}${e.section ? ` §${e.section}` : ''}`
                      : `${e.domain}:${e.usubjid}:${e.seq ?? ''}`}
                  </li>
                ))}
                {answer.evidence.length > 6 && (
                  <li className="ask-more">+{answer.evidence.length - 6} more</li>
                )}
              </ul>
            )}
            <div className="ask-text">{answer.text}</div>
          </>
        )}
      </div>
    )
  }

  return (
    <div
      ref={rootRef}
      className="ask-root"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => { if (!pinned) setOpen(false) }}
    >
      <div ref={scrimRef} className={`ask-scrim ${expanded ? 'is-on' : ''}`} />

      <div ref={cardRef} className={`ask-card ${expanded ? 'is-open' : ''}`}>
        {!expanded ? (
          <div className="ask-pill">
            <Icon name="sparkle" size={15} />
            Ask Atlas
          </div>
        ) : (
          <div className="ask-body u-scroll">
            <div className="ask-head">
              <span className="ask-head-title">
                <Icon name="sparkle" size={16} />
                <span>Ask Atlas</span>
              </span>
              <button
                className="ask-icon-btn"
                onClick={() => { setPinned(false); setOpen(false) }}
                aria-label="Close"
              ><Icon name="close" size={15} /></button>
            </div>

            <input
              ref={inputRef}
              className="input"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onFocus={() => setPinned(true)}
              onKeyDown={(e) => { if (e.key === 'Enter') ask() }}
              placeholder="Which subjects meet Hy's law criteria?"
            />

            <div className="ask-examples">
              {EXAMPLES.map((example) => (
                <button
                  key={example}
                  className="ask-example"
                  onClick={() => { setText(example); setPinned(true) }}
                >
                  <Icon name="arrowRight" size={13} />
                  {example}
                </button>
              ))}
            </div>

            {renderAnswer()}
          </div>
        )}
      </div>
    </div>
  )
}
