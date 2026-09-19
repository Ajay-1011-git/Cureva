import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'framer-motion'
import Icon from '../../components/Icon.jsx'
import { gsap, reducedMotion } from '../../lib/motion.js'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
const PERSONAS = ['SAFETY', 'CLINICAL_OPS', 'REGULATORY']
const LABEL = { SAFETY: 'Safety', CLINICAL_OPS: 'Clinical Ops', REGULATORY: 'Regulatory' }
const SEAT_ICON = { SAFETY: 'shield', CLINICAL_OPS: 'layers', REGULATORY: 'document' }
const REMIT = {
  SAFETY: 'ICH E2A seriousness · is a participant being harmed?',
  CLINICAL_OPS: 'ICH E6(R2) GCP · isolated slip or systemic failure?',
  REGULATORY: 'reporting duty · would the record survive inspection?',
}
const STEPS = ['verdicts', 'cross-examination', 'evidence check']

/** A reviewer's name, always with its icon — used as the speaker on every turn. */
function Speaker({ persona }) {
  return (
    <span className="speaker">
      <Icon name={SEAT_ICON[persona]} size={15} />
      {LABEL[persona] || persona}
    </span>
  )
}

/**
 * A verdict, as a pill. Red is ESCALATE, green is MONITOR, everywhere — but
 * the word is always present, so colour is never carrying the meaning alone.
 */
function Verdict({ value, small = false }) {
  if (!value) return null
  const side = value.toLowerCase()
  return (
    <span className={`verdict-pill is-${side}${small ? ' is-sm' : ''}`}>
      <Icon name={side === 'escalate' ? 'alert' : 'shield'} size={13} strokeWidth={2} />
      {value}
    </span>
  )
}

/** `AE 042-S03-016 #1`, or a document's own name — never `AE:042-S03-016:null`. */
function refLabel(e) {
  if (e.document) return e.section ? `${e.document} §${e.section}` : e.document
  const seq = e.seq === null || e.seq === undefined ? '' : ` #${e.seq}`
  return `${e.domain} ${e.usubjid || ''}${seq}`.replace(/\s+/g, ' ').trim()
}

/**
 * Round 3 carries its citations as one flat `AE:042-S03-016:1, DM:...:None`
 * string. Split back into the same chips round 1 uses, so a citation looks
 * like a citation wherever it appears — and a record with no sequence number
 * reads as having none rather than as the word `None`.
 */
function citeChips(raw) {
  if (!raw) return []
  return raw.split(',').map((part) => {
    const [domain, usubjid, seq] = part.trim().split(':')
    if (!domain) return null
    return refLabel({
      domain,
      usubjid,
      seq: seq === 'None' || seq === '' || seq === undefined ? null : seq,
    })
  }).filter(Boolean)
}

/**
 * Round 3 hands back its claims as flat strings, because that is the shape the
 * evidence check works in. They are rendered as structure, not dumped as text:
 * an opening position and a challenge are different things and should not look
 * alike. Anything that does not match either shape is shown verbatim rather
 * than silently dropped.
 */
function parseClaim(raw) {
  const challenge = raw.match(
    /^\[([A-Z_]+)\s*->\s*([A-Z_]+)\]\s*challenged:\s*([\s\S]*?)\s*\|\s*rebuttal:\s*([\s\S]*)$/)
  if (challenge) {
    return { kind: 'challenge', persona: challenge[1], target: challenge[2],
             quote: challenge[3], text: challenge[4] }
  }
  const position = raw.match(/^\[([A-Z_]+)\]\s*([A-Z]+):\s*([\s\S]*?)(?:\s*\(cites\s*([^)]*)\))?$/)
  if (position) {
    return { kind: 'position', persona: position[1], verdict: position[2],
             text: position[3], cites: position[4] }
  }
  return { kind: 'other', text: raw }
}

/**
 * The deliberation, read as a transcript.
 *
 * It runs top to bottom in the order the argument actually happened — opening
 * positions, then who challenged whom, then what the evidence check let stand.
 * The earlier layout put each challenge inside the card of the reviewer it was
 * aimed at, which meant "Regulatory attacks this" appeared inside Safety's
 * column and the thread of the argument had to be reassembled by eye.
 *
 * Red is ESCALATE, green is MONITOR, throughout — verdict, challenge and
 * ledger row all use the same two, so a reviewer changing sides is visible
 * before you read a word. The word is always there too.
 *
 * Staged deliberately slowly. The transcript is already complete when it
 * arrives — no streaming, per the architecture's explicit decision — so the
 * pacing is a reading aid, not a progress bar pretending work is happening.
 * With reduced motion the whole thing is simply shown at once.
 */
export default function TribunalPanel({ findingId, onClose }) {
  const [transcript, setTranscript] = useState(null)
  const [stage, setStage] = useState(0)   // 0 load · 1 positions · 2 challenges · 3 ledger · 4 verdict
  const [error, setError] = useState(null)
  const rootRef = useRef(null)

  useEffect(() => {
    if (!findingId) return
    let live = true
    setTranscript(null); setStage(0); setError(null)
    fetch(`${API_BASE}/api/monitor/tribunal/${findingId}`)
      .then((r) => r.json())
      .then((d) => { if (live) setTranscript(d) })
      .catch((e) => { if (live) setError(String(e.message || e)) })
    return () => { live = false }
  }, [findingId])

  useEffect(() => {
    if (!transcript?.ran) return
    if (reducedMotion()) { setStage(4); return }
    const tl = gsap.timeline()
    tl.call(() => setStage(1)).to({}, { duration: 1.5 })
      .call(() => setStage(2)).to({}, { duration: 2.0 })
      .call(() => setStage(3)).to({}, { duration: 1.2 })
      .call(() => setStage(4))
    return () => tl.kill()
  }, [transcript])

  useEffect(() => {
    if (!rootRef.current || stage === 0 || reducedMotion()) return
    const sel = { 1: '.turn', 2: '.exchange', 3: '.ledger-row', 4: '.room-verdict' }[stage]
    if (!sel) return
    const nodes = rootRef.current.querySelectorAll(sel)
    if (!nodes.length) return
    gsap.fromTo(nodes,
      { opacity: 0, y: stage === 2 ? -8 : 16 },
      { opacity: 1, y: 0, duration: 0.55, stagger: 0.12, ease: 'power3.out' })
  }, [stage])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose?.() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // The transcript scrolls inside the overlay; the page behind it should not
  // scroll with it.
  useEffect(() => {
    if (!findingId) return
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = previous }
  }, [findingId])

  if (!findingId) return null

  /**
   * Rendered into <body>, never in place.
   *
   * The panel's own slot on /monitor sits inside a `[data-reveal]` section, and
   * the reveal puts a transform on it. A transformed ancestor becomes the
   * containing block for `position: fixed`, so an in-place overlay was sized to
   * that one column instead of the viewport, and its z-index was trapped in the
   * ancestor's stacking context — which is how the run-cycle bar and the header
   * ended up painted over the top of it. A portal leaves both problems behind.
   */
  const shell = (children) => createPortal(
    <AnimatePresence>
      <motion.div
        className="room-scrim"
        onClick={(e) => { if (e.target === e.currentTarget) onClose?.() }}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.26 }}
        role="dialog"
        aria-modal="true"
        aria-label="Panel deliberation"
      >
        <motion.div
          className="room u-scroll"
          ref={rootRef}
          initial={{ opacity: 0, y: 26, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 16, scale: 0.98 }}
          transition={{ duration: 0.38, ease: [0.22, 1, 0.36, 1] }}
        >
          {children}
        </motion.div>
      </motion.div>
    </AnimatePresence>,
    document.body,
  )

  const closeButton = (
    <button className="btn btn-ghost btn-sm" onClick={onClose}>
      <Icon name="close" size={13} /> Close
    </button>
  )

  if (error) {
    return shell(
      <div className="room-hollow">
        <Icon name="alert" size={26} strokeWidth={1.4} />
        <h3>Could not load the deliberation.</h3>
        <p>{error}</p>
        {closeButton}
      </div>
    )
  }

  if (!transcript) {
    return shell(
      <div className="room-hollow">
        <span className="ask-thinking"><i /><i /><i /></span>
        <p>Opening the room…</p>
      </div>
    )
  }

  if (!transcript.ran) {
    return shell(
      <>
        <div className="room-bar">
          <div className="room-title"><h2>Deliberation</h2></div>
          {closeButton}
        </div>
        <div className="room-hollow">
          <Icon name="scales" size={26} strokeWidth={1.4} />
          <h3>No deliberation was held for this finding.</h3>
          <p>{transcript.skip_reason}</p>
          <p className="room-fine">
            Its verdict is the rule-based one and is complete standing alone — the
            panel only ever adds argument on top. This is shown as an absence, not
            dressed up as agreement.
          </p>
        </div>
      </>
    )
  }

  const arb = transcript.round3
  const revised = (p) => transcript.round2.find((r) => r.persona === p)?.revised_verdict
  const openingOf = (p) => transcript.round1.find((v) => v.persona === p)
  const finalOf = (p) => revised(p) || openingOf(p)?.verdict

  // In the order the argument happened: each reviewer's challenges, in turn.
  const exchanges = transcript.round2.flatMap((r) =>
    r.challenges.map((c) => ({ from: r.persona, to: c.target_persona,
                               quote: c.claim_challenged, rebuttal: c.rebuttal })))
  const flips = PERSONAS
    .filter((p) => revised(p) && revised(p) !== openingOf(p)?.verdict)
    .map((p) => ({ persona: p, from: openingOf(p)?.verdict, to: revised(p) }))

  const positions = [...new Set(transcript.round1.map((v) => v.verdict))]
  const split = positions.length > 1
  const escalateVotes = PERSONAS.filter((p) => finalOf(p) === 'ESCALATE').length
  const monitorVotes = PERSONAS.filter((p) => finalOf(p) === 'MONITOR').length

  const surviving = (arb?.surviving_claims || []).map((c) => ({ ...parseClaim(c), held: true }))
  const discarded = (arb?.discarded_claims || []).map((d) => ({
    ...parseClaim(d.claim), held: false, reason: d.reason_discarded,
    persona: d.persona || parseClaim(d.claim).persona,
  }))
  const ledger = [...surviving, ...discarded]

  const roundHead = (n, title, note) => (
    <div className="round-head">
      <span className="round-n">Round {n}</span>
      <h3>{title}</h3>
      {note && <em>{note}</em>}
    </div>
  )

  return shell(
    <>
      <div className="room-bar">
        <div className="room-title">
          <h2>Deliberation</h2>
          <em>
            {transcript.round1.length} reviewers · {exchanges.length} challenges ·{' '}
            {transcript.tokens_used} tokens · {transcript.duration_ms}ms
          </em>
        </div>

        <div className="room-steps">
          {STEPS.map((s, i) => (
            <span key={s} className={`room-step ${stage > i ? 'is-on' : ''}`}>
              <i />{s}
            </span>
          ))}
        </div>

        {closeButton}
      </div>

      {stage >= 1 && split && (
        <div className="room-split">
          <Icon name="alert" size={13} />
          the panel is split — {positions.join(' vs ')}
        </div>
      )}

      {/* ---------------------------------------- round 1: opening positions */}
      {stage >= 1 && (
        <section className="round">
          {roundHead(1, 'Opening positions', 'each reviewer reads the finding on their own remit, before hearing the others')}

          <div className="thread">
            {PERSONAS.map((p) => {
              const v = openingOf(p)
              if (!v) {
                return (
                  <article className="turn is-silent" key={p}>
                    <div className="turn-head">
                      <Speaker persona={p} />
                      <span className="turn-silent">no verdict — this reviewer fell silent</span>
                    </div>
                  </article>
                )
              }
              return (
                <article className={`turn is-${v.verdict.toLowerCase()}`} key={p}>
                  <div className="turn-head">
                    <Speaker persona={p} />
                    <Verdict value={v.verdict} />
                  </div>
                  <p className="turn-remit">{REMIT[p]}</p>
                  <p className="turn-body">{v.reasoning}</p>
                  {v.cited_evidence?.length > 0 && (
                    <div className="turn-cites">
                      <span className="cites-label">cites</span>
                      <ul className="ref-list">
                        {v.cited_evidence.map((e, i) => (
                          <li key={i} className={`ref ${e.document ? 'ref-doc' : ''}`}>{refLabel(e)}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </article>
              )
            })}
          </div>
        </section>
      )}

      {/* ------------------------------------- round 2: cross-examination */}
      {stage >= 2 && (
        <section className="round">
          {roundHead(2, 'Cross-examination', 'each reviewer now answers the others, quoting the claim they are attacking')}

          {exchanges.length === 0 ? (
            <p className="round-none">
              No one challenged anyone — the panel agreed on first reading, so there
              was nothing to cross-examine.
            </p>
          ) : (
            <div className="thread">
              {exchanges.map((x, i) => (
                <article className="exchange" key={i}>
                  <div className="exchange-head">
                    <Speaker persona={x.from} />
                    <Icon name="arrowRight" size={14} className="exchange-arrow" />
                    <Speaker persona={x.to} />
                  </div>
                  <blockquote className="exchange-quote">{x.quote}</blockquote>
                  <p className="exchange-rebuttal">{x.rebuttal}</p>
                </article>
              ))}
            </div>
          )}

          {flips.length > 0 && (
            <ul className="flip-list">
              {flips.map((f) => (
                <li key={f.persona}>
                  <Icon name="refresh" size={13} />
                  <span>
                    <strong>{LABEL[f.persona]}</strong> was persuaded — {f.from} → {f.to}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {/* ------------------------------------------ round 3: evidence check */}
      {stage >= 3 && arb && (
        <section className="round">
          {roundHead(3, 'Evidence check',
            'every citation re-read against the study’s own records — no model involved')}

          <div className="ledger-tally">
            <span className="tag tag-good"><Icon name="check" size={12} /> {surviving.length} held</span>
            <span className="tag tag-crit"><Icon name="close" size={12} /> {discarded.length} struck</span>
          </div>

          <ul className="ledger">
            {ledger.map((c, i) => (
              <li className={`ledger-row ${c.held ? 'is-held' : 'is-struck'}`} key={i}>
                <Icon name={c.held ? 'check' : 'close'} size={14} strokeWidth={2.2}
                      className="ledger-mark" />
                <div className="ledger-main">
                  <div className="ledger-head">
                    {c.persona && <Speaker persona={c.persona} />}
                    {c.kind === 'challenge' && c.target && (
                      <span className="ledger-kind">challenge to {LABEL[c.target] || c.target}</span>
                    )}
                    {c.kind === 'position' && <Verdict value={c.verdict} small />}
                  </div>
                  {c.quote && <blockquote className="ledger-quote">{c.quote}</blockquote>}
                  <p className="ledger-claim">{c.text}</p>
                  {citeChips(c.cites).length > 0 && (
                    <div className="turn-cites">
                      <span className="cites-label">cites</span>
                      <ul className="ref-list">
                        {citeChips(c.cites).map((label, j) => (
                          <li key={j} className="ref">{label}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {c.reason && (
                    <p className="ledger-reason">
                      <strong>struck:</strong> {c.reason}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* ------------------------------------------------- the final verdict */}
      {stage >= 4 && arb && (
        <div className="room-verdict">
          <div className="room-tally">
            <span className="tag tag-crit">{escalateVotes} escalate</span>
            <span className="tag tag-good">{monitorVotes} monitor</span>
          </div>

          <div className={`room-final is-${arb.final_verdict.toLowerCase()}`}>
            <Icon name={arb.final_verdict === 'ESCALATE' ? 'alert' : 'shield'}
                  size={40} strokeWidth={2} />
            {arb.final_verdict}
          </div>

          <p className="room-note">
            {arb.surviving_claims.length} claim(s) survived the evidence check,
            {' '}{arb.discarded_claims.length} discarded.
            {' '}Decided without a model — every citation was checked against the
            study's own records.
          </p>

          <div className="room-caveat">
            <Icon name="alert" size={14} />
            <span>
              The evidence check verifies the study records each reviewer cited. Any
              guideline or clause number in their arguments is the reviewer's own and
              is <strong>not</strong> verified here — read it as their reasoning, not
              as a confirmed citation.
            </span>
          </div>
        </div>
      )}
    </>
  )
}
