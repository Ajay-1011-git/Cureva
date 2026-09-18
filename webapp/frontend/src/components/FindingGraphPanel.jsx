import { useEffect, useMemo, useRef, useState } from 'react'
import FindingGraph3D, { hexFor } from './FindingGraph3D.jsx'
import FindingDetail from './FindingDetail.jsx'

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
 * Layout is a deterministic cluster layout, not a force simulation: clusters
 * are placed on a ring and their members on a smaller ring inside it. At this
 * node count a force sim costs a lot of frames to converge and lands somewhere
 * slightly different every reload, which makes it useless for narrating a demo
 * twice in a row. This is stable, instant, and readable.
 */



function layout(nodes, clusters) {
  const pos = new Map()
  const byId = new Map(nodes.map((n) => [n.finding_id, n]))
  // Big clusters first so they get the roomier outer slots.
  const ordered = [...clusters].sort((a, b) => b.length - a.length)
  const cx = W / 2
  const cy = H / 2

  ordered.forEach((cluster, ci) => {
    // Clusters spiral outward: index 0 near the middle, later ones further
    // out, so a large connected group reads as the centre of the picture.
    const ang = ci * 2.399963           // golden angle — avoids visible spokes
    const rad = 34 + Math.sqrt(ci) * 46
    const gx = cx + Math.cos(ang) * rad
    const gy = cy + Math.sin(ang) * rad * 0.72

    if (cluster.length === 1) {
      pos.set(cluster[0], { x: gx, y: gy })
      return
    }
    const r = Math.min(46, 11 + cluster.length * 2.6)
    cluster.forEach((id, i) => {
      const a = (i / cluster.length) * Math.PI * 2
      pos.set(id, { x: gx + Math.cos(a) * r, y: gy + Math.sin(a) * r })
    })
  })

  // Anything the backend didn't put in a cluster still needs a home.
  nodes.forEach((n, i) => {
    if (!pos.has(n.finding_id)) {
      pos.set(n.finding_id, { x: 30 + (i * 37) % (W - 60), y: 30 + (i * 53) % (H - 60) })
    }
  })
  return { pos, byId }
}

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


  const codes = useMemo(() => {
    const counts = {}
    snapshot.nodes.forEach((n) => { counts[n.code] = (counts[n.code] || 0) + 1 })
    return Object.entries(counts).sort((a, b) => b[1] - a[1])
  }, [snapshot])


  const newCount = newIds.current.size
  const subjectNodes = snapshot.nodes.filter((n) => n.usubjid === subject).length

  return (
    <div className="finding-graph-panel">
      <div className="fg-header">
        <h2>Finding graph</h2>
        <span className="fg-stats">
          {snapshot.nodes.length} findings · {snapshot.edges.length} links ·{' '}
          {snapshot.clusters.length} clusters
        </span>
      </div>

      <div className="fg-legend">
        <button className={`fg-chip${!codeFilter ? ' active' : ''}`}
                onClick={() => setCodeFilter(null)}>all</button>
        {codes.map(([code, n]) => (
          <button key={code}
                  className={`fg-chip${codeFilter === code ? ' active' : ''}`}
                  onClick={() => setCodeFilter(codeFilter === code ? null : code)}
                  title={`${code} — ${n}`}>
            <i style={{ background: hexFor(code) }} />
            {code.replace(/_/g, ' ').toLowerCase()} <b>{n}</b>
          </button>
        ))}
      </div>

      {error && <div className="fg-empty">Could not load the graph: {error}</div>}

      {snapshot.nodes.length === 0 && !error ? (
        <div className="fg-empty">No findings yet.</div>
      ) : (
        <div className="fg-body">
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

      <div className="fg-footer">
        <span className="fg-key"><i className="k-subject" /> this subject ({subjectNodes})</span>
        <span className="fg-key"><i className="k-new" /> added this session ({newCount})</span>
      </div>
    </div>
  )
}
