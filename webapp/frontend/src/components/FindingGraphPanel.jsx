import { useEffect, useMemo, useRef, useState } from 'react'
import FindingGraph3D from './FindingGraph3D.jsx'
import FindingDetail from './FindingDetail.jsx'
import Icon from './Icon.jsx'
import { groupCodesByFamily, labelFor } from '../lib/findingCodes.js'

/**
 * Act 2 — the whole finding graph over the real study, drawn as a graph.
 *
 * It is seeded at backend startup by running every detector across the study,
 * so the panel shows the real picture (≈190 nodes) from the first page load
 * rather than an empty box. A conversation then ADDS to it, and anything the
 * current session contributed is drawn differently — that contrast is the
 * whole demo: here is what the data already says, now watch a patient add to
 * it by speaking.
 *
 * The legend is grouped by family because that is what colour encodes. Each
 * chip still names its code, and clicking one isolates it — so the reader who
 * needs per-code identity gets it from the word and the filter, which is the
 * honest way to carry twelve categories through five hues.
 */
export default function FindingGraphPanel({ apiBase, refreshKey, subject,
                                            onSelectSubject }) {
  const [snapshot, setSnapshot] = useState(
    { nodes: [], edges: [], clusters: [], centrality: {} })
  const [codeFilter, setCodeFilter] = useState(null)
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState(null)
  const seenIds = useRef(null)          // null until the first load completes
  const newIds = useRef(new Set())
  const reportCounts = useRef(new Map())

  useEffect(() => {
    let cancelled = false
    fetch(`${apiBase}/api/atlas/finding-graph`)
      .then((r) => r.json())
      .then((data) => {
        if (cancelled) return
        const ids = new Set(data.nodes.map((n) => n.finding_id))
        if (seenIds.current === null) {
          // First load is the seeded baseline — nothing is "new" yet.
          newIds.current = new Set()
        } else {
          // Accumulate across the whole session rather than diffing one poll
          // against the last. A patient-reported node is created once and then
          // GROWS as the person says more, so a per-poll diff would light it
          // up for one turn and then forget it — and "added this session"
          // would read 0 while the conversation was still adding to it.
          for (const id of ids) {
            if (!seenIds.current.has(id)) newIds.current.add(id)
          }
          // A node that gained new patient-reported terms counts as touched
          // this session too, even though its id is not new.
          for (const n of data.nodes) {
            const before = reportCounts.current.get(n.finding_id) ?? null
            const now = (n.reported || []).length
            if (before !== null && now > before) newIds.current.add(n.finding_id)
          }
        }
        for (const n of data.nodes) {
          reportCounts.current.set(n.finding_id, (n.reported || []).length)
        }
        seenIds.current = ids
        setSnapshot(data)
        setError(null)
      })
      .catch((e) => setError(String(e)))
    return () => { cancelled = true }
  }, [apiBase, refreshKey])

  const families = useMemo(() => {
    const counts = {}
    snapshot.nodes.forEach((n) => { counts[n.code] = (counts[n.code] || 0) + 1 })
    return groupCodesByFamily(Object.entries(counts))
  }, [snapshot])

  const newCount = newIds.current.size
  const subjectNodes = snapshot.nodes.filter((n) => n.usubjid === subject).length

  return (
    <div className="card graph-card">
      <div className="card-head">
        <div className="u-col" style={{ gap: 6 }}>
          <span className="tag tag-ink">
            <Icon name="graph" size={13} />
            Finding graph
          </span>
        </div>
        <span className="t-caption t-quiet t-num">
          {snapshot.nodes.length} findings · {snapshot.edges.length} links ·{' '}
          {snapshot.clusters.length} clusters
        </span>
      </div>

      <div className="graph-legend">
        <div className="graph-family">
          <span className="graph-family-name">
            <Icon name="filter" size={12} />
            All families
          </span>
          <button className={`graph-chip${!codeFilter ? ' is-on' : ''}`}
                  onClick={() => setCodeFilter(null)}>
            show everything <b>{snapshot.nodes.length}</b>
          </button>
        </div>

        {families.map(({ family, codes, total }) => (
          <div className="graph-family" key={family.id}>
            <span className="graph-family-name" title={family.blurb}>
              <i style={{ background: family.color }} />
              {family.label} <b className="t-num">{total}</b>
            </span>
            {codes.map(([code, n]) => (
              <button key={code}
                      className={`graph-chip${codeFilter === code ? ' is-on' : ''}`}
                      onClick={() => setCodeFilter(codeFilter === code ? null : code)}
                      title={`${code} — ${n} finding(s)`}>
                <i style={{ background: family.color }} />
                {labelFor(code)} <b>{n}</b>
              </button>
            ))}
          </div>
        ))}
      </div>

      {error && (
        <div className="graph-empty">
          <Icon name="alert" size={24} strokeWidth={1.4} />
          Could not load the graph — {error}
        </div>
      )}

      {snapshot.nodes.length === 0 && !error ? (
        <div className="graph-empty">
          <Icon name="graph" size={26} strokeWidth={1.4} />
          No findings yet.
        </div>
      ) : (
        <div className="graph-body">
          <FindingGraph3D
            snapshot={snapshot}
            subject={subject}
            newIds={newIds.current}
            codeFilter={codeFilter}
            selectedId={selected?.finding_id || null}
            onSelect={(id) => setSelected(
              id ? snapshot.nodes.find((n) => n.finding_id === id) || null : null)}
          />
          <FindingDetail node={selected} onClose={() => setSelected(null)}
                         onSelectSubject={onSelectSubject} />
        </div>
      )}

      <div className="graph-foot">
        <span className="graph-key">
          <i className="k-subject" /> this subject <b className="t-num">({subjectNodes})</b>
        </span>
        <span className="graph-key">
          <i className="k-new" /> added this session <b className="t-num">({newCount})</b>
        </span>
        <span className="t-quiet" style={{ marginLeft: 'auto' }}>
          colour is the family · the chip names the code
        </span>
      </div>
    </div>
  )
}
