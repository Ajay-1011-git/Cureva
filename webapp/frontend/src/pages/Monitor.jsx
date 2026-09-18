import { useCallback, useEffect, useState } from 'react'
import HumanGate from './Monitor/HumanGate.jsx'
import TribunalPanel from './Monitor/TribunalPanel.jsx'
import PageHero from '../components/PageHero.jsx'
import Icon from '../components/Icon.jsx'
import { useReveal, useCountUp, useMagnetic } from '../lib/motion.js'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

/**
 * One tile, one number. These are stat tiles rather than a chart on purpose:
 * eight quantities in five different units have no shared scale, and a bar
 * chart across them would draw a comparison that does not exist.
 *
 * The value uses the font's proportional figures — tabular widths are for
 * columns that must line up vertically, and at 34px they make a three-digit
 * number look gappy.
 */
function StatTile({ label, value, suffix = '', tone }) {
  const ref = useCountUp(value)
  return (
    <div className={`stat${tone ? ` stat-${tone}` : ''}`} data-reveal data-reveal-group="stats">
      <div className="stat-value"><span ref={ref} />{suffix}</div>
      <div className="stat-label">{label}</div>
    </div>
  )
}

/**
 * The review-cycle page (T2.19): run a cycle, watch the panel deliberate, and
 * answer the escalations it raises.
 *
 * Reuses the shared layout and its page-enter transition; nothing about the
 * page shell is rebuilt here.
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
  // Which slice of the gate is on screen. PENDING is the worklist and the
  // right default, but a decided escalation must stay reachable — you often
  // only want the argument *after* you have made the call, and filtering it
  // off screen left no way back to it.
  const [gateFilter, setGateFilter] = useState('PENDING')

  const runRef = useMagnetic({ strength: 5 })

  const loadGate = useCallback(async (state = gateFilter) => {
    try {
      const res = await fetch(`${API_BASE}/api/monitor/escalations?state=${state}`)
      setGate(await res.json())
    } catch (err) {
      setError(String(err.message || err))
    }
  }, [gateFilter])

  useEffect(() => { loadGate(gateFilter) }, [loadGate, gateFilter])

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

  const bodyRef = useReveal([Boolean(report), gateFilter])

  return (
    <div className="page">
      <PageHero
        eyebrow="Act 2 · Review cycle"
        eyebrowIcon="scales"
        title="Six nodes. One data cut. One human call."
        sub="Detect, judge, query, check the protocol, escalate, report. Everything below is the real cycle's output — no fixtures, no replay."
      />

      <div className="console">
        <div className="console-card">
          <label className="field">
            <span className="t-eyebrow">Data cut</span>
            <input className="input input-num" type="number" min="1" max="12" value={cut}
                   onChange={(e) => setCut(e.target.value)} />
          </label>
          <label className="field">
            <span className="t-eyebrow">Protocol</span>
            <input className="input input-num" type="number" min="1" max="3" value={protocolVersion}
                   onChange={(e) => setProtocolVersion(e.target.value)} />
          </label>

          <span className="console-spacer" />

          <button ref={runRef} className="btn btn-primary" onClick={runCycle} disabled={busy}>
            {busy
              ? <><span className="ask-thinking"><i /><i /><i /></span> running…</>
              : <><Icon name="play" size={14} /> Run cycle</>}
          </button>
          <button className="btn btn-ghost" onClick={reset} disabled={busy}
                  title="Clear memory and restage">
            <Icon name="refresh" size={14} /> Reset
          </button>
        </div>
      </div>

      <div className="page-body" ref={bodyRef}>
        <div className="l-workspace">
          {error && (
            <div className="notice notice-crit" style={{ marginBottom: 24 }}>
              <Icon name="alert" size={16} />
              <span><strong>Could not reach the backend.</strong> {error}</span>
            </div>
          )}

          {report && (
            <div className="stats">
              <StatTile label="Findings in this cut" value={report.findings.length} />
              <StatTile label="Escalation-worthy" tone="crit"
                        value={verdicts.filter((v) => v.escalate).length} />
              <StatTile label="Watch only" tone="good"
                        value={verdicts.filter((v) => !v.escalate).length} />
              <StatTile label="Queries raised" value={report.queries.length} />
              <StatTile label="Protocol deviations" value={report.deviations.length} />
              <StatTile label="Trace lines written" value={report.trace.length} />
              <StatTile label="Protocol version" value={report.protocol_version} suffix="" />
              <StatTile label="Cycle duration" value={report.duration_ms} suffix="ms" />
            </div>
          )}

          {report && (
            <p className="run-note" data-reveal>
              {deliberated.length > 0
                ? `${deliberated.length} contested finding(s) went to the three-reviewer panel this cycle.`
                : 'No panel deliberation completed this cycle — every verdict below is the rule-based one, which is complete on its own.'}
              {' '}Queries and escalations already raised in an earlier cycle are not raised again.
            </p>
          )}

          <div className="review-grid">
            <section className="review-col" data-reveal data-reveal-group="gate">
              <div className="col-head">
                <h2>Human gate</h2>
                <p>
                  Every escalation waits here for a decision. Approve, reject, or ask
                  for clarification — clarification is answered from the graph and
                  resubmitted. Decided ones stay reachable: switch the filter to argue
                  one after the fact.
                </p>
              </div>
              <HumanGate
                escalations={gate.escalations}
                counts={gate.counts}
                busy={busy}
                onDecided={loadGate}
                onSelectFinding={setFindingId}
                onDebate={debate}
                filter={gateFilter}
                onFilter={setGateFilter}
                debating={debating}
              />
            </section>

            <section className="review-col" data-reveal data-reveal-group="panel">
              <div className="col-head">
                <h2>Deliberation</h2>
                <p>
                  Three reviewers argue a contested finding, then every claim they
                  made is checked against the study's own records.
                </p>
              </div>

              {debating && (
                <div className="panel-placeholder">
                  <span className="ask-thinking"><i /><i /><i /></span>
                  <p>
                    Three reviewers are arguing this finding. The free tier throttles
                    on tokens per minute, so this can take up to 45 seconds.
                  </p>
                </div>
              )}

              {findingId ? (
                <TribunalPanel findingId={findingId} onClose={() => setFindingId(null)} />
              ) : deliberated.length > 0 ? (
                <div className="panel-picker">
                  {deliberated.map((v) => (
                    <button key={v.finding_id} className="btn btn-ghost btn-sm"
                            onClick={() => setFindingId(v.finding_id)}>
                      <Icon name="scales" size={13} />
                      {v.code} · {v.usubjid || v.site}
                    </button>
                  ))}
                </div>
              ) : !debating && (
                <div className="panel-placeholder">
                  <Icon name="scales" size={26} strokeWidth={1.4} />
                  <p>Pick an escalation with a deliberation, or run a cycle to produce one.</p>
                </div>
              )}
            </section>
          </div>
        </div>
      </div>
    </div>
  )
}
