import { useEffect, useRef, useState } from 'react'
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

/**
 * The deliberation, shown as an argument rather than a list.
 *
 * It opens as a full-screen room because the point of the third round is that
 * you can watch a claim get struck down — that does not read in a sidebar.
 * Red is ESCALATE, green is MONITOR, throughout: the same two colours carry
 * verdict, challenge and stamp, so the moment a panel flips sides is visible
 * without reading a word. The word is always there too — colour is never the
 * only signal.
 *
 * Staged deliberately slowly. The transcript is already complete when it
 * arrives — no streaming, per the architecture's explicit decision — so the
 * pacing is a reading aid, not a progress bar pretending work is happening.
 * With reduced motion the whole thing is simply shown at once, because the
 * pacing is the decoration here, not the content.
 */
export default function TribunalPanel({ findingId, onClose }) {
  const [transcript, setTranscript] = useState(null)
  const [stage, setStage] = useState(0)   // 0 load · 1 verdicts · 2 challenges · 3 stamps · 4 consensus
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
    const sel = { 1: '.seat', 2: '.seat-attack', 3: '.seat-stamp', 4: '.room-verdict' }[stage]
    if (!sel) return
    const nodes = rootRef.current.querySelectorAll(sel)
    if (!nodes.length) return
    gsap.fromTo(nodes,
      { opacity: 0, scale: stage === 3 ? 1.35 : 0.97, y: stage === 2 ? -10 : 18 },
      { opacity: 1, scale: 1, y: 0, duration: stage === 3 ? 0.5 : 0.6,
        stagger: 0.14, ease: stage === 3 ? 'back.out(2.4)' : 'power3.out' })
  }, [stage])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose?.() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  if (!findingId) return null

  const shell = (children) => (
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
    </AnimatePresence>
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
  const finalOf = (p) => revised(p) || transcript.round1.find((v) => v.persona === p)?.verdict
  const attacksOn = (p) => transcript.round2.flatMap((r) =>
    r.challenges.filter((c) => c.target_persona === p).map((c) => ({ ...c, from: r.persona })))
  const struck = (p) => arb?.discarded_claims.some(
    (d) => d.persona === p && d.claim.startsWith(`[${p}]`))

  const positions = [...new Set(transcript.round1.map((v) => v.verdict))]
  const split = positions.length > 1
  const totalAttacks = transcript.round2.reduce((n, r) => n + r.challenges.length, 0)
  const escalateVotes = PERSONAS.filter((p) => finalOf(p) === 'ESCALATE').length
  const monitorVotes = PERSONAS.filter((p) => finalOf(p) === 'MONITOR').length

  return shell(
    <>
      <div className="room-bar">
        <div className="room-title">
          <h2>Deliberation</h2>
          <em>
            {transcript.round1.length} reviewers · {totalAttacks} challenges ·{' '}
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

      <div className="room-floor">
        {PERSONAS.map((p) => {
          const v = transcript.round1.find((x) => x.persona === p)
          if (!v) {
            return (
              <div className="seat is-mute" key={p}>
                <div className="seat-who">
                  <span className="seat-name">
                    <Icon name={SEAT_ICON[p]} size={16} />
                    {LABEL[p]}
                  </span>
                  <em className="seat-remit">no verdict — this reviewer fell silent</em>
                </div>
              </div>
            )
          }
          const side = (finalOf(p) || 'MONITOR').toLowerCase()
          const attacks = stage >= 2 ? attacksOn(p) : []
          const isStruck = stage >= 3 && struck(p)
          const changed = revised(p) && revised(p) !== v.verdict

          return (
            <div className={`seat is-${side}${isStruck ? ' is-struck' : ''}`} key={p}>
              <div className="seat-who">
                <span className="seat-name">
                  <Icon name={SEAT_ICON[p]} size={16} />
                  {LABEL[p]}
                </span>
                <em className="seat-remit">{REMIT[p]}</em>
              </div>

              <div className={`seat-call is-${side}`}>
                <Icon name={side === 'escalate' ? 'alert' : 'shield'} size={22} strokeWidth={2} />
                {finalOf(p)}
              </div>
              {changed && (
                <span className="seat-flip">
                  <Icon name="refresh" size={11} /> changed from {v.verdict}
                </span>
              )}

              <p className={`seat-argument ${attacks.length ? 'is-under-fire' : ''}`}>
                {v.reasoning}
              </p>

              <div className="seat-refs">
                <ul className="ref-list">
                  {v.cited_evidence.map((e, i) => (
                    <li key={i} className="ref">{e.domain}:{e.usubjid}:{e.seq ?? '—'}</li>
                  ))}
                </ul>
              </div>

              {attacks.map((c, i) => (
                <div className="seat-attack" key={i}>
                  <div className="seat-attack-head">
                    <Icon name="alert" size={11} />
                    {LABEL[c.from]} attacks this
                  </div>
                  <div className="seat-attack-quote">“{c.claim_challenged}”</div>
                  <div className="seat-attack-body">{c.rebuttal}</div>
                </div>
              ))}

              {stage >= 3 && (
                <div className={`seat-stamp ${isStruck ? 'is-failed' : 'is-held'}`}>
                  <Icon name={isStruck ? 'close' : 'check'} size={14} strokeWidth={2.2} />
                  {isStruck ? 'evidence failed' : 'evidence held'}
                </div>
              )}
            </div>
          )
        })}
      </div>

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

          {arb.discarded_claims.length > 0 && (
            <ul className="room-killed">
              {arb.discarded_claims.map((d, i) => (
                <li key={i}>
                  <Icon name="close" size={13} strokeWidth={2.2} />
                  <span><strong>{LABEL[d.persona] || d.persona}</strong> — {d.reason_discarded}</span>
                </li>
              ))}
            </ul>
          )}

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
