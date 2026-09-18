import { useEffect, useMemo, useRef, useState } from 'react'
import gsap from 'gsap'

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

const CODE_COLOURS = {
  HYS_LAW_CANDIDATE: '#ef5350',
  SAE_MISCODED: '#ff7043',
  EXCLUSION_VIOLATION: '#ffa726',
  INCLUSION_VIOLATION: '#ffca28',
  DOSING_ERROR: '#ab47bc',
  PROHIBITED_CONMED: '#7e57c2',
  AE_BEFORE_FIRST_DOSE: '#42a5f5',
  DUPLICATE_SUBJECT: '#26c6da',
  MISSING_EXPOSURE_RECORD: '#26a69a',
  LAB_UNIT_MISMATCH: '#66bb6a',
  VISIT_OUT_OF_WINDOW: '#78909c',
  // What the patient said, not what a detector found — deliberately the
  // accent colour so it reads as 'added by this conversation'.
  PATIENT_REPORTED: '#4fc3f7',
}
const colourFor = (code) => CODE_COLOURS[code] || '#8a97a6'

const W = 760
const H = 560

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

export default function FindingGraphPanel({ apiBase, refreshKey, subject }) {
  const [snapshot, setSnapshot] = useState(
    { nodes: [], edges: [], clusters: [], centrality: {} })
  const [codeFilter, setCodeFilter] = useState(null)
  const [hovered, setHovered] = useState(null)
  const [error, setError] = useState(null)
  const seenIds = useRef(null)          // null until the first load completes
  const newIds = useRef(new Set())
  const svgRef = useRef(null)

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
          newIds.current = new Set([...ids].filter((id) => !seenIds.current.has(id)))
        }
        seenIds.current = ids
        setSnapshot(data)
        setError(null)
      })
      .catch((e) => setError(String(e)))
    return () => { cancelled = true }
  }, [apiBase, refreshKey])

  const { pos } = useMemo(
    () => layout(snapshot.nodes, snapshot.clusters), [snapshot])

  // Animate in anything that appeared since the last poll.
  useEffect(() => {
    if (!svgRef.current || newIds.current.size === 0) return
    const sel = svgRef.current.querySelectorAll('[data-new="1"]')
    if (sel.length) {
      gsap.fromTo(sel, { scale: 0, opacity: 0, transformOrigin: '50% 50%' },
        { scale: 1, opacity: 1, duration: 0.7, ease: 'back.out(2)', stagger: 0.08 })
    }
  }, [snapshot])

  const codes = useMemo(() => {
    const counts = {}
    snapshot.nodes.forEach((n) => { counts[n.code] = (counts[n.code] || 0) + 1 })
    return Object.entries(counts).sort((a, b) => b[1] - a[1])
  }, [snapshot])

  const visible = (n) =>
    (!codeFilter || n.code === codeFilter)

  const shownNodes = snapshot.nodes.filter(visible)
  const shownIds = new Set(shownNodes.map((n) => n.finding_id))
  const shownEdges = snapshot.edges.filter(
    (e) => shownIds.has(e.from_finding_id) && shownIds.has(e.to_finding_id))

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
            <i style={{ background: colourFor(code) }} />
            {code.replace(/_/g, ' ').toLowerCase()} <b>{n}</b>
          </button>
        ))}
      </div>

      {error && <div className="fg-empty">Could not load the graph: {error}</div>}

      {snapshot.nodes.length === 0 && !error ? (
        <div className="fg-empty">No findings yet.</div>
      ) : (
        <svg ref={svgRef} className="fg-svg" viewBox={`0 0 ${W} ${H}`}
             data-testid="finding-graph-svg">
          {shownEdges.map((e, i) => {
            const a = pos.get(e.from_finding_id)
            const b = pos.get(e.to_finding_id)
            if (!a || !b) return null
            return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                         className={`fg-edge fg-edge-${e.relation}`} />
          })}
          {shownNodes.map((n) => {
            const p = pos.get(n.finding_id)
            if (!p) return null
            const isNew = newIds.current.has(n.finding_id)
            const isSubject = n.usubjid === subject
            const fromPatient = (n.derived_from || []).includes('PRO')
            const hub = snapshot.centrality[n.finding_id] || 0
            const r = 4.5 + Math.min(5, hub * 55) + (isSubject ? 1.6 : 0)
            return (
              <g key={n.finding_id} data-new={isNew ? '1' : '0'}
                 onMouseEnter={() => setHovered(n)} onMouseLeave={() => setHovered(null)}>
                {(isNew || fromPatient) && (
                  <circle cx={p.x} cy={p.y} r={r + 5} className="fg-node-halo" />
                )}
                <circle
                  cx={p.x} cy={p.y} r={r}
                  fill={colourFor(n.code)}
                  className={`fg-node${isSubject ? ' subject' : ''}${fromPatient ? ' from-patient' : ''}`}
                  data-code={n.code}
                  data-usubjid={n.usubjid || ''}
                />
              </g>
            )
          })}
        </svg>
      )}

      <div className="fg-footer">
        <span className="fg-key"><i className="k-subject" /> this subject ({subjectNodes})</span>
        <span className="fg-key"><i className="k-new" /> added this session ({newCount})</span>
        {hovered && (
          <span className="fg-hover">
            <b>{hovered.code.replace(/_/g, ' ')}</b> · {hovered.usubjid || hovered.site}
            {(hovered.derived_from || []).length > 0 &&
              <> · from {hovered.derived_from.join(', ')}</>}
          </span>
        )}
      </div>
    </div>
  )
}
