import { useEffect, useRef, useState } from 'react'
import gsap from 'gsap'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
const PERSONAS = ['SAFETY', 'CLINICAL_OPS', 'REGULATORY']

/**
 * The three-round reveal (T2.20): Round 1 verdicts fill in, Round 2 challenges
 * strike through the specific claims they dispute, Round 3 stamps each claim
 * survived or discarded, then a consensus banner.
 *
 * The whole transcript arrives in one response and is animated client-side.
 * That is the architecture's explicit no-streaming decision, not a shortcut:
 * the deliberation is already finished server-side by the time anything is
 * shown, so streaming would only be theatre over a completed result.
 *
 * A discarded claim is struck through and stamped, never removed. The point of
 * Round 3 is that you can see what was thrown out and why — a panel that
 * silently dropped it would look identical to one where it was never said.
 */
export default function TribunalPanel({ findingId, onClose }) {
  const [transcript, setTranscript] = useState(null)
  const [stage, setStage] = useState(0)     // 0 none, 1 verdicts, 2 challenges, 3 stamps
  const [error, setError] = useState(null)
  const rootRef = useRef(null)

  useEffect(() => {
    if (!findingId) return
    setTranscript(null); setStage(0); setError(null)
    fetch(`${API_BASE}/api/monitor/tribunal/${findingId}`)
      .then((r) => r.json())
      .then(setTranscript)
      .catch((e) => setError(String(e.message || e)))
  }, [findingId])

  // Sequence the reveal once the transcript is in.
  useEffect(() => {
    if (!transcript?.ran) return
    const timeline = gsap.timeline()
    timeline.call(() => setStage(1))
      .to({}, { duration: 0.9 })
      .call(() => setStage(2))
      .to({}, { duration: 1.1 })
      .call(() => setStage(3))
    return () => timeline.kill()
  }, [transcript])

  // Fade each card in as its stage arrives.
  useEffect(() => {
    if (!rootRef.current || stage === 0) return
    gsap.fromTo(rootRef.current.querySelectorAll('.trb-card'),
      { opacity: 0, y: 14 },
      { opacity: 1, y: 0, duration: 0.45, stagger: 0.12, ease: 'power2.out' })
  }, [stage])

  if (!findingId) return null

  if (error) {
    return <div className="trb-wrap"><div className="trb-empty">could not load: {error}</div></div>
  }
  if (!transcript) {
    return <div className="trb-wrap"><div className="trb-empty">loading deliberation…</div></div>
  }

  if (!transcript.ran) {
    // An honest absence, shown as one. Never dressed up as agreement.
    return (
      <div className="trb-wrap">
        <div className="trb-head">
          <span>Deliberation</span>
          <button className="trb-close" onClick={onClose}>×</button>
        </div>
        <div className="trb-empty">
          <strong>No deliberation ran for this finding.</strong>
          <p>{transcript.skip_reason}</p>
          <p className="trb-note">
            The verdict you see on this finding is the rule-based one, and it is
            complete on its own — the deliberation only ever adds narrative.
          </p>
        </div>
      </div>
    )
  }

  const arb = transcript.round3
  const challengesAgainst = (persona) =>
    transcript.round2.flatMap((r) =>
      r.challenges.filter((c) => c.target_persona === persona)
        .map((c) => ({ ...c, from: r.persona })))

  const claimVerdict = (persona) => {
    if (!arb || stage < 3) return null
    const discarded = arb.discarded_claims.find(
      (d) => d.persona === persona && d.claim.startsWith(`[${persona}]`))
    return discarded ? { ok: false, why: discarded.reason_discarded } : { ok: true }
  }

  const positions = [...new Set(transcript.round1.map((v) => v.verdict))]

  return (
    <div className="trb-wrap" ref={rootRef}>
      <div className="trb-head">
        <span>Deliberation · {transcript.round1.length} reviewers · {transcript.tokens_used} tokens · {transcript.duration_ms}ms</span>
        <button className="trb-close" onClick={onClose}>×</button>
      </div>

      <div className="trb-grid">
        {PERSONAS.map((persona) => {
          const verdict = transcript.round1.find((v) => v.persona === persona)
          if (!verdict) {
            return (
              <div className="trb-card trb-silent" key={persona}>
                <div className="trb-persona">{persona.replace('_', ' ')}</div>
                <div className="trb-empty-small">no verdict this round</div>
              </div>
            )
          }
          const against = stage >= 2 ? challengesAgainst(persona) : []
          const stamp = claimVerdict(persona)
          return (
            <div className={`trb-card ${stamp ? (stamp.ok ? 'trb-kept' : 'trb-struck') : ''}`} key={persona}>
              <div className="trb-persona">{persona.replace('_', ' ')}</div>
              <div className={`trb-verdict trb-${verdict.verdict.toLowerCase()}`}>
                {verdict.verdict}
              </div>
              <p className={`trb-reason ${against.length ? 'trb-disputed' : ''}`}>
                {verdict.reasoning}
              </p>
              <div className="trb-cites">
                {verdict.cited_evidence.map((e, i) => (
                  <span key={i}>{e.domain}:{e.usubjid}:{e.seq ?? '—'}</span>
                ))}
              </div>

              {against.map((c, i) => (
                <div className="trb-challenge" key={i}>
                  <div className="trb-challenge-from">{c.from.replace('_', ' ')} disputes this</div>
                  <div className="trb-challenge-text">{c.rebuttal}</div>
                </div>
              ))}

              {stamp && (
                <div className={`trb-stamp ${stamp.ok ? 'ok' : 'bad'}`}>
                  {stamp.ok ? '✓ evidence verified' : '✗ discarded'}
                  {!stamp.ok && <div className="trb-stamp-why">{stamp.why}</div>}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {stage >= 3 && arb && (
        <div className="trb-consensus">
          <div className="trb-consensus-head">
            Round 3 · {arb.method.replace(/_/g, ' ')} · zero model calls
          </div>
          <div className="trb-consensus-body">
            <strong>{arb.final_verdict}</strong>
            {' — '}
            {positions.length > 1
              ? `the panel split ${positions.join(' vs ')}; `
              : 'the panel agreed; '}
            {arb.surviving_claims.length} claim(s) survived the evidence check,
            {' '}{arb.discarded_claims.length} discarded.
          </div>
          {arb.discarded_claims.length > 0 && (
            <ul className="trb-discarded">
              {arb.discarded_claims.map((d, i) => (
                <li key={i}><strong>{d.persona}</strong> — {d.reason_discarded}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
