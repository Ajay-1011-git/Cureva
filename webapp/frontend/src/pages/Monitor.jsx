import { useCallback, useEffect, useState } from 'react'
import HumanGate from './Monitor/HumanGate.jsx'
import TribunalPanel from './Monitor/TribunalPanel.jsx'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

/**
 * The review-cycle page (T2.19): run a cycle, watch the panel deliberate, and
 * answer the escalations it raises.
 *
 * Reuses the shared layout and its GSAP page-enter transition; nothing about
 * the page shell is rebuilt here.
 */
export default function Monitor() {
  const [cut, setCut] = useState(9)
  const [protocolVersion, setProtocolVersion] = useState(3)
  const [result, setResult] = useState(null)
  const [gate, setGate] = useState({ escalations: [], counts: {} })
  const [findingId, setFindingId] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [debating, setDebating] = useState(null)

  const loadGate = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/monitor/escalations?state=PENDING`)
      setGate(await res.json())
    } catch (err) {
      setError(String(err.message || err))
    }
  }, [])

  useEffect(() => { loadGate() }, [loadGate])

  const runCycle = useCallback(async () => {
    setBusy(true); setError(null); setFindingId(null)
    try {
      const res = await fetch(`${API_BASE}/api/monitor/run-cycle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cut: Number(cut), protocol_version: Number(protocolVersion) }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setResult(data)
      await loadGate()
    } catch (err) {
      setError(String(err.message || err))
    } finally {
      setBusy(false)
    }
  }, [cut, protocolVersion, loadGate])

  // Deliberating on demand, because the cycle's own budget is one finding and
  // the interesting one is whichever a person is looking at.
  const debate = useCallback(async (fid) => {
    setDebating(fid)
    try {
      await fetch(`${API_BASE}/api/monitor/tribunal/${fid}/run`, { method: 'POST' })
      await loadGate()
      setFindingId(fid)
    } catch (err) {
      setError(String(err.message || err))
    } finally {
      setDebating(null)
    }
  }, [loadGate])

  const reset = useCallback(async () => {
    setBusy(true)
    try {
      await fetch(`${API_BASE}/api/monitor/reset`, { method: 'POST' })
      setResult(null); setFindingId(null)
      await loadGate()
    } finally { setBusy(false) }
  }, [loadGate])

  const report = result?.report
  const verdicts = result?.verdicts || []
  const deliberated = verdicts.filter((v) => v.tribunal_ran)

  return (
    <div className="mon-page">
      <header className="mon-header">
        <div>
          <h1>Review cycle</h1>
          <p className="mon-sub">
            Six nodes over one data cut — detect, judge, query, check the protocol,
            escalate, report. Everything below is the real cycle's output.
          </p>
        </div>
        <div className="mon-controls">
          <label>cut
            <input type="number" min="1" max="12" value={cut}
                   onChange={(e) => setCut(e.target.value)} />
          </label>
          <label>protocol
            <input type="number" min="1" max="3" value={protocolVersion}
                   onChange={(e) => setProtocolVersion(e.target.value)} />
          </label>
          <button className="mon-run" onClick={runCycle} disabled={busy}>
            {busy ? 'running…' : 'Run cycle'}
          </button>
          <button className="mon-reset" onClick={reset} disabled={busy} title="Clear memory and restage">
            Reset
          </button>
        </div>
      </header>

      {error && <div className="mon-error">could not reach the backend — {error}</div>}

      {report && (
        <div className="mon-stats">
          {[
            ['findings', report.findings.length],
            ['escalation-worthy', verdicts.filter((v) => v.escalate).length],
            ['watch-only', verdicts.filter((v) => !v.escalate).length],
            ['queries', report.queries.length],
            ['deviations', report.deviations.length],
            ['trace lines', report.trace.length],
            ['protocol', `v${report.protocol_version}`],
            ['duration', `${report.duration_ms}ms`],
          ].map(([label, value]) => (
            <div className="mon-stat" key={label}>
              <div className="mon-stat-value">{value}</div>
              <div className="mon-stat-label">{label}</div>
            </div>
          ))}
        </div>
      )}

      {report && (
        <p className="mon-note">
          {deliberated.length > 0
            ? `${deliberated.length} contested finding(s) went to the three-reviewer panel this cycle.`
            : 'No panel deliberation completed this cycle — every verdict below is the rule-based one, which is complete on its own.'}
          {' '}Queries and escalations already raised in an earlier cycle are not raised again.
        </p>
      )}

      <div className="mon-split">
        <section className="mon-col">
          <h2>Human gate</h2>
          <p className="mon-colsub">
            Every escalation waits here for a decision. Approve, reject, or ask for
            clarification — clarification is answered from the graph and resubmitted.
          </p>
          <HumanGate
            escalations={gate.escalations}
            counts={gate.counts}
            busy={busy}
            onDecided={loadGate}
            onSelectFinding={setFindingId}
            onDebate={debate}
          />
        </section>

        <section className="mon-col">
          <h2>Deliberation</h2>
          <p className="mon-colsub">
            Three reviewers argue a contested finding, then every claim they made is
            checked against the study's own records.
          </p>
          {debating && (
            <div className="trb-empty">
              three reviewers are arguing this finding… the free tier throttles on
              tokens per minute, so this can take up to 45 seconds.
            </div>
          )}
          {findingId ? (
            <TribunalPanel findingId={findingId} onClose={() => setFindingId(null)} />
          ) : deliberated.length > 0 ? (
            <div className="mon-picker">
              {deliberated.map((v) => (
                <button key={v.finding_id} onClick={() => setFindingId(v.finding_id)}>
                  {v.code} · {v.usubjid || v.site}
                </button>
              ))}
            </div>
          ) : (
            <div className="trb-empty">
              Pick an escalation with a deliberation, or run a cycle to produce one.
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
