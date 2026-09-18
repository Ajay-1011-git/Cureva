import { useCallback, useState } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

/**
 * The human gate (T2.21) — the screen a judge uses to stand in for the medical
 * monitor during a live defence.
 *
 * Each decision posts to the real endpoint and the row updates from what came
 * back, never from what the button optimistically assumed. CLARIFY is shown
 * working, not just flickering: the row states that the system is answering
 * from the graph and resubmitting, and the resulting state and clarify_count
 * are what the server actually returned.
 */
export default function HumanGate({ escalations, counts, onDecided, onSelectFinding, busy }) {
  const [pending, setPending] = useState({})   // escalation_id -> the decision in flight
  const [results, setResults] = useState({})   // escalation_id -> the record returned

  const decide = useCallback(async (escalationId, decision) => {
    setPending((p) => ({ ...p, [escalationId]: decision }))
    try {
      const res = await fetch(`${API_BASE}/api/monitor/escalations/${escalationId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const record = await res.json()
      setResults((r) => ({ ...r, [escalationId]: record }))
      onDecided?.(record)
    } catch (err) {
      setResults((r) => ({ ...r, [escalationId]: { _error: String(err.message || err) } }))
    } finally {
      setPending((p) => { const next = { ...p }; delete next[escalationId]; return next })
    }
  }, [onDecided])

  if (busy) return <div className="hg-empty">running the cycle…</div>

  if (!escalations?.length) {
    return (
      <div className="hg-empty">
        <strong>Nothing is waiting for a decision.</strong>
        <p>
          Run a cycle to raise escalations. If you have already run this cut, memory
          is doing its job — an escalation answered once is never raised again.
          Reset to restage the demo.
        </p>
      </div>
    )
  }

  return (
    <div className="hg-list">
      <div className="hg-counts">
        {Object.entries(counts || {}).map(([state, n]) => (
          <span key={state} className={`hg-count hg-${state.toLowerCase()}`}>{state} {n}</span>
        ))}
      </div>

      {escalations.map((e) => {
        const inFlight = pending[e.escalation_id]
        const result = results[e.escalation_id]
        const state = result?.state || e.state
        const clarified = (result?.clarify_count ?? e.clarify_count) > 0

        return (
          <div className={`hg-row hg-state-${state.toLowerCase()}`} key={e.escalation_id}>
            <div className="hg-main">
              <div className="hg-title">
                <span className={`hg-sev hg-sev-${(e.severity || 'MEDIUM').toLowerCase()}`}>
                  {e.severity || '—'}
                </span>
                <strong>{e.code}</strong>
                <span className="hg-subject">{e.usubjid || e.site || 'study-level'}</span>
                {e.has_tribunal && (
                  <button className="hg-link" onClick={() => onSelectFinding?.(e.finding_id)}>
                    see the deliberation
                  </button>
                )}
              </div>
              <div className="hg-summary">{e.summary}</div>
              <div className="hg-evidence">
                {e.evidence.slice(0, 5).map((ref, i) => (
                  <span key={i}>
                    {ref.document
                      ? `${ref.document}${ref.section ? ` §${ref.section}` : ''}`
                      : `${ref.domain}:${ref.usubjid}:${ref.seq ?? '—'}`}
                  </span>
                ))}
                {e.evidence.length > 5 && <span>+{e.evidence.length - 5} more</span>}
              </div>

              {result?._error && <div className="hg-error">{result._error}</div>}

              {inFlight === 'CLARIFY' && (
                <div className="hg-working">
                  answering from the graph and resubmitting…
                </div>
              )}

              {result && !result._error && (
                <div className="hg-outcome">
                  <strong>{state}</strong>
                  {clarified && <span className="hg-clarified">
                    · clarified {result.clarify_count}× then resubmitted
                  </span>}
                  {result.reason && <div className="hg-reason">{result.reason}</div>}
                </div>
              )}
            </div>

            <div className="hg-actions">
              {state === 'PENDING' ? (
                ['APPROVED', 'REJECTED', 'CLARIFY'].map((d) => (
                  <button
                    key={d}
                    className={`hg-btn hg-btn-${d.toLowerCase()}`}
                    disabled={!!inFlight}
                    onClick={() => decide(e.escalation_id, d)}
                  >
                    {inFlight === d ? '…' : d === 'APPROVED' ? 'Approve'
                      : d === 'REJECTED' ? 'Reject' : 'Clarify'}
                  </button>
                ))
              ) : (
                <div className={`hg-final hg-${state.toLowerCase()}`}>{state}</div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
