import { useEffect, useRef, useState } from 'react'
import gsap from 'gsap'

/**
 * Live finding-graph panel (T1.32). Polls GET /api/atlas/finding-graph after
 * each avatar turn (`refreshKey` bump) and animates newly-appeared nodes in
 * with a simple scale/fade — infrastructure-level polish, not the showcase
 * animation itself, per the build instructions' own scoping note.
 */
export default function FindingGraphPanel({ apiBase, refreshKey }) {
  const [snapshot, setSnapshot] = useState({ nodes: [], edges: [], clusters: [], centrality: {} })
  const seenIds = useRef(new Set())
  const containerRef = useRef(null)

  useEffect(() => {
    let cancelled = false
    fetch(`${apiBase}/api/atlas/finding-graph`)
      .then((r) => r.json())
      .then((data) => { if (!cancelled) setSnapshot(data) })
      .catch((err) => console.warn('finding-graph poll failed', err))
    return () => { cancelled = true }
  }, [apiBase, refreshKey])

  useEffect(() => {
    if (!containerRef.current) return
    const newNodes = containerRef.current.querySelectorAll('[data-new-node="1"]')
    if (newNodes.length) {
      gsap.fromTo(newNodes, { scale: 0.4, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.5, ease: 'back.out(1.7)', stagger: 0.06 })
    }
  }, [snapshot])

  const clusterOf = (id) => snapshot.clusters.findIndex((c) => c.includes(id))

  return (
    <div className="finding-graph-panel">
      <div className="fg-header">
        <h2>Finding graph</h2>
        <span className="fg-stats">{snapshot.nodes.length} nodes · {snapshot.edges.length} edges · {snapshot.clusters.length} clusters</span>
      </div>
      {snapshot.nodes.length === 0 ? (
        <div className="fg-empty">No findings yet — accumulates as the avatar conversation maps onto real signals.</div>
      ) : (
        <div className="fg-nodes" ref={containerRef}>
          {snapshot.nodes.map((n) => {
            const isNew = !seenIds.current.has(n.finding_id)
            seenIds.current.add(n.finding_id)
            const centrality = snapshot.centrality[n.finding_id] ?? 0
            return (
              <div
                key={n.finding_id}
                className="fg-node"
                data-new-node={isNew ? '1' : '0'}
                title={n.finding_id}
                style={{ '--hub': Math.min(1, centrality * 8) }}
              >
                <div className="fg-node-code">{n.code}</div>
                <div className="fg-node-subject">{n.usubjid || n.site || '—'}</div>
                <div className="fg-node-cluster">cluster {clusterOf(n.finding_id) + 1}</div>
              </div>
            )
          })}
        </div>
      )}
      {snapshot.edges.length > 0 && (
        <div className="fg-edges">
          {snapshot.edges.slice(0, 8).map((e, i) => (
            <div key={i} className="fg-edge-row">
              <span>{e.from_finding_id.split('|')[0]}</span>
              <span className="fg-edge-rel">{e.relation}</span>
              <span>{e.to_finding_id.split('|')[0]}</span>
            </div>
          ))}
          {snapshot.edges.length > 8 && <div className="fg-edge-more">+{snapshot.edges.length - 8} more</div>}
        </div>
      )}
    </div>
  )
}
