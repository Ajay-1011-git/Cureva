import { useCallback, useState } from 'react'
import ForecastChart from './Watch/ForecastChart.jsx'
import Artifacts from './Watch/Artifacts.jsx'
import SurveillanceReport from './Watch/SurveillanceReport.jsx'
import PageHero from '../components/PageHero.jsx'
import Icon from '../components/Icon.jsx'
import { useReveal, useCountUp, useMagnetic } from '../lib/motion.js'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

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
 * The surveillance page (T3.21): walk twelve data cuts, then read what the
 * period produced.
 *
 * Three sections on one page, in the order a reviewer needs them: where sites
 * are heading, what paperwork that generated, and the report itself with its
 * decision log. Reuses the shared layout and its page-enter transition; the
 * shell is not rebuilt here.
 *
 * `run-period` is one request and one response, deliberately. It runs for a
 * few seconds, and the honest way to show that is a progress indicator rather
 * than a stream — a stream would be a second code path narrating the same
 * walk, and the two would drift apart the first time one of them changed.
 */
export default function Watch() {
  const [result, setResult] = useState(null)
  const [forecast, setForecast] = useState(null)
  const [artifacts, setArtifacts] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [explanation, setExplanation] = useState(null)

  const runRef = useMagnetic({ strength: 5 })

  const runPeriod = useCallback(async () => {
    setBusy(true); setError(null); setExplanation(null)
    try {
      const res = await fetch(`${API_BASE}/api/watch/run-period`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cuts: Array.from({ length: 12 }, (_, i) => i + 1) }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setResult(await res.json())
      const [f, a] = await Promise.all([
        fetch(`${API_BASE}/api/watch/forecast`).then((r) => r.json()),
        fetch(`${API_BASE}/api/watch/artifacts`).then((r) => r.json()),
      ])
      setForecast(f); setArtifacts(a)
    } catch (err) {
      setError(String(err.message || err))
    } finally {
      setBusy(false)
    }
  }, [])

  // `explain` is the behaviour judges pick decisions to test, so the drawer
  // shows the raw trace lines as well as the assembled answer — the point is
  // that the two are the same thing, and hiding the lines would mean asking to
  // be believed rather than showing the file.
  const explain = useCallback(async (decisionId) => {
    setExplanation({ loading: true, id: decisionId })
    try {
      const res = await fetch(`${API_BASE}/api/watch/explain/${decisionId}`)
      setExplanation({ ...(await res.json()), id: decisionId })
    } catch (err) {
      setExplanation({ error: String(err.message || err), id: decisionId })
    }
  }, [])

  const report = result?.report
  const budget = report?.budget
  const bodyRef = useReveal([Boolean(report)])

  return (
    <div className="page">
      <PageHero
        eyebrow="Acts 4 & 5 · Surveillance period"
        eyebrowIcon="pulse"
        title="Twelve cuts. Corrections, a slow reviewer, and a document that lies."
        sub="The whole period, walked end to end. Everything below is this run's real output — no fixtures, no replay, and no language model anywhere in the decision path."
      />

      <div className="console">
        <div className="console-card">
          <span className="t-body-sm t-quiet">
            Walks cuts 1–12, the full public period.
          </span>
          <span className="console-spacer" />
          <button ref={runRef} className="btn btn-primary" onClick={runPeriod} disabled={busy}>
            {busy
              ? <><span className="ask-thinking"><i /><i /><i /></span> walking the period…</>
              : <><Icon name="play" size={14} /> Run the period</>}
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

          {busy && !report && (
            <p className="run-note" data-reveal>
              Twelve real review cycles, each re-filtering the study at its own
              cut. This takes a few seconds and returns once, complete.
            </p>
          )}

          {report && (
            <div className="stats">
              <StatTile label="Cuts walked" value={result.cuts.length} />
              <StatTile label="Distinct signals" value={report.signals.length} />
              <StatTile label="Escalations raised" value={report.escalations.length} />
              <StatTile label="Decisions reached" tone="good" value={report.decisions.length} />
              <StatTile label="Still awaiting a human" tone="crit"
                        value={report.escalations.filter((e) => e.decision === 'PENDING').length} />
              <StatTile label="Documents drafted" value={artifacts?.count ?? 0} />
              <StatTile label="Model tokens spent" value={budget?.tokens?.spent ?? 0} />
              <StatTile label="Period duration" value={result.duration_ms} suffix="ms" />
            </div>
          )}

          {report && (
            <p className="run-note" data-reveal>
              {report.escalations.filter((e) => e.decision === 'PENDING').length} escalation(s)
              are still open at the end of the period — some because the reviewer
              never answered, some because they were raised too near the end to be
              due yet. Neither is treated as approval.
              {' '}<strong>{budget?.tokens?.spent ?? 0} language-model tokens</strong> were
              spent reaching these decisions.
            </p>
          )}

          {report && (
            <>
              <section className="watch-section" data-reveal>
                <div className="section-head">
                  <h2 className="t-heading-sm">Where sites are heading</h2>
                  <span className="t-caption t-quiet">
                    {forecast?.count ?? 0} forecast(s), each attached to a real decision
                  </span>
                </div>
                <ForecastChart rows={forecast?.forecasts} />
              </section>

              <section className="watch-section" data-reveal>
                <div className="section-head">
                  <h2 className="t-heading-sm">Paperwork drafted</h2>
                  <span className="t-caption t-quiet">
                    only from decisions the monitor approved
                  </span>
                </div>
                <Artifacts data={artifacts} />
              </section>

              <section className="watch-section" data-reveal>
                <div className="section-head">
                  <h2 className="t-heading-sm">The surveillance report</h2>
                  <span className="t-caption t-quiet">
                    the graded object's own `markdown` field, rendered
                  </span>
                </div>
                <SurveillanceReport report={report} onExplain={explain} />
              </section>
            </>
          )}

          {!report && !busy && !error && (
            <div className="card watch-empty" data-reveal>
              <Icon name="clock" size={18} />
              <p className="t-body">
                Nothing has been walked yet. Press <strong>Run the period</strong> to
                review all twelve data cuts — corrections landing late, a reviewer
                who answers slowly or not at all, a site whose glucose values
                change scale overnight, and a lab manual that asks to be obeyed.
              </p>
            </div>
          )}
        </div>
      </div>

      {explanation && (
        <div className="watch-drawer-scrim" onClick={() => setExplanation(null)}>
          <aside className="watch-drawer" onClick={(e) => e.stopPropagation()}
                 role="dialog" aria-label="Why this decision was made">
            <header className="watch-drawer-head">
              <div>
                <span className="t-eyebrow">Why this decision was made</span>
                <h3 className="t-mono t-body">{explanation.id}</h3>
              </div>
              <button className="ask-icon-btn" onClick={() => setExplanation(null)}
                      aria-label="Close">
                <Icon name="close" size={16} />
              </button>
            </header>

            {explanation.loading && <p className="t-body t-quiet">Reading the trace…</p>}
            {explanation.error && (
              <div className="notice notice-crit"><Icon name="alert" size={15} />
                <span>{explanation.error}</span></div>
            )}

            {explanation.explanation && (
              <div className="watch-drawer-body">
                <p className="t-body-lg">{explanation.explanation.what}</p>

                <div className={`notice ${explanation.found ? '' : 'notice-warn'}`}>
                  <Icon name={explanation.found ? 'check' : 'alert'} size={15} />
                  <span>
                    {explanation.found
                      ? <>Reconstructed from <strong>{explanation.explanation.evidence_lines.length} trace
                          line(s)</strong> written as the period ran. Nothing here was
                          regenerated, and no model was asked.</>
                      : <>No decision with this id appears in the trace. Nothing is
                          inferred from that — no explanation is offered rather than a
                          plausible one.</>}
                  </span>
                </div>

                {explanation.explanation.evidence.length > 0 && (
                  <>
                    <h4 className="t-eyebrow">Records cited</h4>
                    <ul className="watch-drawer-refs">
                      {explanation.explanation.evidence.map((r, i) => (
                        <li key={i} className="t-mono t-body-sm">
                          {r.domain}{r.usubjid ? ` ${r.usubjid}` : ''}
                          {r.seq != null ? ` seq ${r.seq}` : ''}
                          {r.document ? ` ${r.document}` : ''}
                        </li>
                      ))}
                    </ul>
                  </>
                )}

                {explanation.explanation.evidence_lines.length > 0 && (
                  <>
                    <h4 className="t-eyebrow">The trace, exactly as written</h4>
                    <ol className="watch-drawer-trace">
                      {explanation.explanation.evidence_lines.map((l, i) => (
                        <li key={i} className="t-mono t-body-sm">{l}</li>
                      ))}
                    </ol>
                    <p className="t-caption t-quiet">
                      These lines are read from{' '}
                      <span className="t-mono">{(explanation.trace_files || []).join(', ')}</span>.
                      Every field above appears verbatim in that file.
                    </p>
                  </>
                )}
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  )
}
