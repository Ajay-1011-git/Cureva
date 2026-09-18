import { useCallback, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import Icon from '../../components/Icon.jsx'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

const DECISIONS = [
  { id: 'APPROVED', label: 'Approve', icon: 'check',   tone: 'good' },
  { id: 'REJECTED', label: 'Reject',  icon: 'close',   tone: 'crit' },
  { id: 'CLARIFY',  label: 'Clarify', icon: 'refresh', tone: 'warn' },
]
const STATE_TONE = { APPROVED: 'good', REJECTED: 'crit', PENDING: 'warn' }
const STATE_ICON = { APPROVED: 'check', REJECTED: 'close', PENDING: 'clock' }

/**
 * The human gate (T2.21) — the screen a judge uses to stand in for the medical
 * monitor during a live defence.
 *
 * Each decision posts to the real endpoint and the row updates from what came
 * back, never from what the button optimistically assumed. CLARIFY is shown
 * working, not just flickering: the row states that the system is answering
 * from the graph and resubmitting, and the resulting state and clarify_count
 * are what the server actually returned.
 *
 * Rows animate with framer-motion `layout` so that switching the filter, or
 * deciding one escalation, reflows the list instead of cutting to a new one —
 * when a row leaves you can see which row it was.
 */
export default function HumanGate({ escalations, counts, onDecided, onSelectFinding,
                                    onDebate, busy, filter = 'PENDING', onFilter,
                                    debating }) {
  const [pending, setPending] = useState({})   // escalation_id -> the decision in flight
  const [results, setResults] = useState({})   // escalation_id -> the record returned
  const [picked, setPicked] = useState(() => new Set())
  const [bulk, setBulk] = useState(null)       // the bulk decision in flight
  const [bulkResult, setBulkResult] = useState(null)

  const pendingRows = (escalations || []).filter(
    (e) => (results[e.escalation_id]?.state || e.state) === 'PENDING')

  const toggle = (id) => setPicked((prev) => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })
  const allPicked = pendingRows.length > 0 && pendingRows.every(
    (e) => picked.has(e.escalation_id))
  const toggleAll = () => setPicked(
    allPicked ? new Set() : new Set(pendingRows.map((e) => e.escalation_id)))

  // One request for the whole selection, rather than one per row. Each item
  // still goes through the same decide() server-side, so a bulk CLARIFY really
  // does read the graph and resubmit for every one of them.
  const decideMany = useCallback(async (decision, everything = false) => {
    setBulk(decision); setBulkResult(null)
    try {
      const body = everything
        ? { decision, all_in_state: 'PENDING' }
        : { decision, escalation_ids: [...picked] }
      const res = await fetch(`${API_BASE}/api/monitor/escalations/bulk`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setBulkResult(data)
      setPicked(new Set())
      onDecided?.(data)
    } catch (err) {
      setBulkResult({ _error: String(err.message || err) })
    } finally {
      setBulk(null)
    }
  }, [picked, onDecided])

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

  const renderRefs = (evidence) => (
    <ul className="ref-list">
      {evidence.slice(0, 5).map((ref, i) => (
        <li key={i} className={`ref${ref.document ? ' ref-doc' : ''}`}>
          {ref.document
            ? `${ref.document}${ref.section ? ` §${ref.section}` : ''}`
            : `${ref.domain}:${ref.usubjid}:${ref.seq ?? '—'}`}
        </li>
      ))}
      {evidence.length > 5 && <li className="ref ref-doc">+{evidence.length - 5} more</li>}
    </ul>
  )

  if (busy) {
    return (
      <div className="panel-placeholder">
        <span className="ask-thinking"><i /><i /><i /></span>
        <p>Running the cycle…</p>
      </div>
    )
  }

  if (!escalations?.length) {
    const decided = (counts?.APPROVED || 0) + (counts?.REJECTED || 0)
    return (
      <div className="gate-empty">
        <Icon name="check" size={26} strokeWidth={1.4} />
        <strong>
          {filter === 'PENDING' && decided
            ? 'Nothing left to decide.'
            : 'Nothing is waiting for a decision.'}
        </strong>
        <p>
          {filter === 'PENDING' && decided
            ? `You have answered ${decided}. They are still here — switch the filter above to see them, or to argue one after the fact.`
            : 'Run a cycle to raise escalations. If you have already run this cut, memory is doing its job — an escalation answered once is never raised again.'}
        </p>
        {filter !== 'ALL' && (
          <button className="btn btn-ghost btn-sm" onClick={() => onFilter?.('ALL')}>
            <Icon name="filter" size={13} /> Show all
          </button>
        )}
      </div>
    )
  }

  return (
    <div>
      {/* The counts double as the filter — one control, not two. */}
      <div className="gate-filters">
        {['PENDING', 'APPROVED', 'REJECTED'].map((state) => (
          <button key={state}
                  className={`gate-filter f-${state.toLowerCase()} ${filter === state ? 'is-on' : ''}`}
                  onClick={() => onFilter?.(state)}>
            <i />{state} <b>{counts?.[state] ?? 0}</b>
          </button>
        ))}
        <button className={`gate-filter f-all ${filter === 'ALL' ? 'is-on' : ''}`}
                onClick={() => onFilter?.('ALL')}>
          <i />ALL <b>{Object.values(counts || {}).reduce((a, b) => a + b, 0)}</b>
        </button>
      </div>

      <div className="gate-bulk">
        <label className="gate-check">
          <input type="checkbox" checked={allPicked} onChange={toggleAll}
                 disabled={!pendingRows.length} />
          <span>{picked.size ? `${picked.size} selected` : `select all ${pendingRows.length} shown`}</span>
        </label>
        <div className="gate-bulk-actions">
          {DECISIONS.map((d) => (
            <button key={d.id} className={`btn btn-ghost btn-xs btn-${d.tone}`}
                    disabled={!picked.size || !!bulk}
                    onClick={() => decideMany(d.id)}>
              {bulk === d.id ? '…' : <><Icon name={d.icon} size={12} /> {d.label} selected</>}
            </button>
          ))}
          <button className="btn btn-ghost btn-xs btn-warn" disabled={!!bulk}
                  onClick={() => decideMany('APPROVED', true)}
                  title="Approve every pending escalation, not just the page shown">
            {bulk === 'APPROVED' ? '…' : <><Icon name="check" size={12} /> Approve all pending</>}
          </button>
        </div>
      </div>

      <AnimatePresence>
        {bulkResult && (
          <motion.div
            className={`gate-bulkresult ${bulkResult._error ? 'is-error' : ''}`}
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
          >
            <Icon name={bulkResult._error ? 'alert' : 'check'} size={14} />
            {bulkResult._error
              ? bulkResult._error
              : `${bulkResult.applied} of ${bulkResult.requested} applied as ${bulkResult.decision}`
                + (bulkResult.failed ? ` · ${bulkResult.failed} failed` : '')}
          </motion.div>
        )}
      </AnimatePresence>

      <motion.div className="gate-list" layout>
        <AnimatePresence initial={false} mode="popLayout">
          {escalations.map((e) => {
            const inFlight = pending[e.escalation_id]
            const result = results[e.escalation_id]
            const state = result?.state || e.state
            const clarified = (result?.clarify_count ?? e.clarify_count) > 0
            const severity = (e.severity || 'MEDIUM').toUpperCase()
            const sevTone = severity === 'CRITICAL' ? 'crit'
              : severity === 'HIGH' ? 'warn' : 'idle'

            return (
              <motion.div
                key={e.escalation_id}
                layout
                className={`gate-row is-${state.toLowerCase()}`}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.97 }}
                transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
              >
                <div className="gate-main">
                  <div className="gate-title">
                    {state === 'PENDING' && (
                      <input type="checkbox" className="gate-rowcheck"
                             aria-label={`Select ${e.code}`}
                             checked={picked.has(e.escalation_id)}
                             onChange={() => toggle(e.escalation_id)} />
                    )}
                    <span className={`tag tag-${sevTone}`}>{severity}</span>
                    <span className="gate-code">{e.code}</span>
                    <span className="gate-subject">{e.usubjid || e.site || 'study-level'}</span>
                    {e.has_tribunal ? (
                      <button className="btn-link" onClick={() => onSelectFinding?.(e.finding_id)}>
                        see the debate
                      </button>
                    ) : (
                      <button className="btn-link btn-link-quiet"
                              disabled={!!debating}
                              onClick={() => onDebate?.(e.finding_id)}
                              title={e.tribunal_skip_reason || undefined}>
                        {debating === e.finding_id
                          ? 'arguing…'
                          : e.tribunal_attempted ? 'try the debate again' : 'debate this'}
                      </button>
                    )}
                  </div>

                  <div className="gate-summary">{e.summary}</div>
                  <div className="gate-refs">{renderRefs(e.evidence)}</div>

                  {result?._error && (
                    <div className="gate-error"><Icon name="alert" size={12} /> {result._error}</div>
                  )}

                  {!e.has_tribunal && e.tribunal_skip_reason && (
                    <div className="gate-skipped">
                      last debate attempt: {e.tribunal_skip_reason}
                    </div>
                  )}

                  {inFlight === 'CLARIFY' && (
                    <div className="gate-working">
                      <span className="ask-thinking"><i /><i /><i /></span>
                      answering from the graph and resubmitting…
                    </div>
                  )}

                  {result && !result._error && (
                    <div className="gate-outcome">
                      <div className="gate-outcome-head">
                        <span className={`tag tag-${STATE_TONE[state] || 'idle'}`}>
                          <Icon name={STATE_ICON[state] || 'clock'} size={11} />
                          {state}
                        </span>
                        {clarified && (
                          <span className="tag tag-warn">
                            clarified {result.clarify_count}× then resubmitted
                          </span>
                        )}
                      </div>
                      {result.reason && <div className="gate-reason">{result.reason}</div>}
                    </div>
                  )}
                </div>

                <div className="gate-actions">
                  {state === 'PENDING' ? (
                    DECISIONS.map((d) => (
                      <button
                        key={d.id}
                        className={`btn btn-ghost btn-xs btn-${d.tone}`}
                        disabled={!!inFlight}
                        onClick={() => decide(e.escalation_id, d.id)}
                      >
                        {inFlight === d.id ? '…' : <><Icon name={d.icon} size={12} /> {d.label}</>}
                      </button>
                    ))
                  ) : (
                    <span className={`tag tag-${STATE_TONE[state] || 'idle'}`}>
                      <Icon name={STATE_ICON[state] || 'clock'} size={11} />
                      {state}
                    </span>
                  )}
                </div>
              </motion.div>
            )
          })}
        </AnimatePresence>
      </motion.div>
    </div>
  )
}
