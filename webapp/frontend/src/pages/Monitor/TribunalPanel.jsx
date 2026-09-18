import { useEffect, useRef, useState } from 'react'
import gsap from 'gsap'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
const PERSONAS = ['SAFETY', 'CLINICAL_OPS', 'REGULATORY']
const LABEL = { SAFETY: 'Safety', CLINICAL_OPS: 'Clinical Ops', REGULATORY: 'Regulatory' }
const REMIT = {
  SAFETY: 'ICH E2A seriousness · is a participant being harmed?',
  CLINICAL_OPS: 'ICH E6(R2) GCP · isolated slip or systemic failure?',
  REGULATORY: 'reporting duty · would the record survive inspection?',
}

/**
 * The deliberation, shown as an argument rather than a list.
 *
 * It opens as a full-screen room because the point of the third round is that
 * you can watch a claim get struck down — that does not read in a sidebar.
 * Red is ESCALATE, green is MONITOR, throughout: the same two colours carry
 * verdict, challenge and stamp, so the moment a panel flips sides is visible
 * without reading a word.
 *
 * Staged deliberately slowly. The transcript is already complete when it
 * arrives — no streaming, per the architecture's explicit decision — so the
 * pacing is a reading aid, not a progress bar pretending work is happening.
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
    const tl = gsap.timeline()
    tl.call(() => setStage(1)).to({}, { duration: 1.5 })
      .call(() => setStage(2)).to({}, { duration: 2.0 })
      .call(() => setStage(3)).to({}, { duration: 1.2 })
      .call(() => setStage(4))
    return () => tl.kill()
  }, [transcript])

  useEffect(() => {
    if (!rootRef.current || stage === 0) return
    const sel = { 1: '.tb-seat', 2: '.tb-attack', 3: '.tb-stamp', 4: '.tb-verdictbar' }[stage]
    if (!sel) return
    const nodes = rootRef.current.querySelectorAll(sel)
    if (!nodes.length) return
    gsap.fromTo(nodes,
      { opacity: 0, scale: stage === 3 ? 1.5 : 0.96, y: stage === 2 ? -10 : 18 },
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
    <div className="tb-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose?.() }}>
      <div className="tb-room" ref={rootRef}>{children}</div>
    </div>
  )

  if (error) return shell(<div className="tb-hollow">could not load — {error}</div>)
  if (!transcript) return shell(<div className="tb-hollow">opening the room…</div>)

  if (!transcript.ran) {
    return shell(
      <>
        <div className="tb-bar">
          <span>Deliberation</span>
          <button className="tb-x" onClick={onClose}>close</button>
        </div>
        <div className="tb-hollow">
          <h3>No deliberation was held for this finding.</h3>
          <p>{transcript.skip_reason}</p>
          <p className="tb-fine">
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
      <div className="tb-bar">
        <span className="tb-title">
          Deliberation
          <em>{transcript.round1.length} reviewers · {totalAttacks} challenges · {transcript.tokens_used} tokens · {transcript.duration_ms}ms</em>
        </span>
        <div className="tb-steps">
          {['verdicts', 'cross-examination', 'evidence check'].map((s, i) => (
            <span key={s} className={`tb-step ${stage > i ? 'on' : ''}`}>{s}</span>
          ))}
        </div>
        <button className="tb-x" onClick={onClose}>close</button>
      </div>

      {stage >= 1 && split && (
        <div className="tb-split-flag">
          the panel is split — {positions.join(' vs ')}
        </div>
      )}

      <div className="tb-floor">
        {PERSONAS.map((p) => {
          const v = transcript.round1.find((x) => x.persona === p)
          if (!v) {
            return (
              <div className="tb-seat tb-seat-mute" key={p}>
                <div className="tb-who">{LABEL[p]}</div>
                <div className="tb-hollow-sm">no verdict — this reviewer fell silent</div>
              </div>
            )
          }
          const side = (finalOf(p) || 'MONITOR').toLowerCase()
          const attacks = stage >= 2 ? attacksOn(p) : []
          const isStruck = stage >= 3 && struck(p)
          const changed = revised(p) && revised(p) !== v.verdict

          return (
            <div className={`tb-seat tb-${side} ${isStruck ? 'tb-dead' : ''}`} key={p}>
              <div className="tb-who">
                {LABEL[p]}
                <em>{REMIT[p]}</em>
              </div>

              <div className={`tb-call tb-call-${side}`}>
                {finalOf(p)}
                {changed && <span className="tb-flip">changed from {v.verdict}</span>}
              </div>

              <p className={`tb-argument ${attacks.length ? 'tb-under-fire' : ''}`}>
                {v.reasoning}
              </p>

              <div className="tb-refs">
                {v.cited_evidence.map((e, i) => (
                  <span key={i}>{e.domain}:{e.usubjid}:{e.seq ?? '—'}</span>
                ))}
              </div>

              {attacks.map((c, i) => (
                <div className="tb-attack" key={i}>
                  <div className="tb-attack-head">
                    {LABEL[c.from]} attacks this
                  </div>
                  <div className="tb-attack-quote">“{c.claim_challenged}”</div>
                  <div className="tb-attack-body">{c.rebuttal}</div>
                </div>
              ))}

              {stage >= 3 && (
                <div className={`tb-stamp ${isStruck ? 'bad' : 'good'}`}>
                  {isStruck ? '✗ EVIDENCE FAILED' : '✓ EVIDENCE HELD'}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {stage >= 4 && arb && (
        <div className="tb-verdictbar">
          <div className="tb-tally">
            <span className="tb-tally-escalate">{escalateVotes} escalate</span>
            <span className="tb-tally-monitor">{monitorVotes} monitor</span>
          </div>
          <div className={`tb-final tb-final-${arb.final_verdict.toLowerCase()}`}>
            {arb.final_verdict}
          </div>
          <div className="tb-final-note">
            {arb.surviving_claims.length} claim(s) survived the evidence check,
            {' '}{arb.discarded_claims.length} discarded.
            {' '}Decided without a model — every citation was checked against the
            study's own records.
          </div>
          {arb.discarded_claims.length > 0 && (
            <ul className="tb-killed">
              {arb.discarded_claims.map((d, i) => (
                <li key={i}><strong>{LABEL[d.persona] || d.persona}</strong> — {d.reason_discarded}</li>
              ))}
            </ul>
          )}
          <div className="tb-caveat">
            The evidence check verifies the study records each reviewer cited. Any
            guideline or clause number in their arguments is the reviewer's own and
            is <strong>not</strong> verified here — read it as their reasoning, not
            as a confirmed citation.
          </div>
        </div>
      )}
    </>
  )
}
