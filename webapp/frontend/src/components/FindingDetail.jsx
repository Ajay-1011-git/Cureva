import { hexFor } from './FindingGraph3D.jsx'

/**
 * What one node in the finding graph actually is.
 *
 * A dot in a graph is only useful if you can ask it what it represents. This
 * shows the code, the subject, which domains the finding was derived from,
 * the exact records cited as evidence, and — for a patient-reported node —
 * every term the person reported with the verbatim quote behind it, because
 * a PRO record without its quote is indistinguishable from a fabricated one.
 */
export default function FindingDetail({ node, onClose, onSelectSubject }) {
  if (!node) {
    return (
      <div className="fg-detail fg-detail-empty">
        Click any node to see what it is, which records it rests on, and what
        the patient said.
      </div>
    )
  }

  const isPatient = node.code === 'PATIENT_REPORTED'
  const records = node.evidence || []
  const docs = records.filter((e) => e.domain === 'DOC')
  const rows = records.filter((e) => e.domain !== 'DOC')

  return (
    <div className="fg-detail" data-testid="finding-detail">
      <div className="fg-detail-head">
        <span className="fg-detail-code" style={{ color: hexFor(node.code) }}>
          ● {node.code.replace(/_/g, ' ')}
        </span>
        <button className="fg-detail-close" onClick={onClose} title="Close">×</button>
      </div>

      <dl className="fg-detail-grid">
        <dt>Subject</dt>
        <dd>
          {node.usubjid
            ? <button className="fg-link" onClick={() => onSelectSubject?.(node.usubjid)}>
                {node.usubjid}
              </button>
            : '—'}
        </dd>
        <dt>Site</dt><dd>{node.site || '—'}</dd>
        <dt>Visible from</dt><dd>cut {node.cut_available}</dd>
        <dt>Derived from</dt>
        <dd>{(node.derived_from || []).join(', ') || '—'}</dd>
      </dl>

      {isPatient && (
        <div className="fg-detail-section">
          <h4>What the patient said ({(node.reported || []).length})</h4>
          {(node.reported || []).length === 0
            ? <p className="fg-detail-muted">Nothing recorded yet.</p>
            : (node.reported || []).map((r, i) => (
                <div key={i} className="fg-quote">
                  <span className={`chat-tag tag-${r.pro_type}`}>
                    {r.pro_type === 'CONMED_MENTION' ? '℞' : '●'} {r.term}
                  </span>
                  <q>{r.quote}</q>
                </div>
              ))}
        </div>
      )}

      <div className="fg-detail-section">
        <h4>Evidence ({records.length})</h4>
        {rows.length === 0 && docs.length === 0 && (
          <p className="fg-detail-muted">No records cited.</p>
        )}
        {rows.length > 0 && (
          <ul className="fg-evidence">
            {rows.map((e, i) => (
              <li key={i}><code>{e.domain}:{e.usubjid}:{e.seq}</code></li>
            ))}
          </ul>
        )}
        {docs.map((e, i) => (
          <p key={i} className="fg-detail-muted">
            rule from <code>{e.document} §{e.section}</code>
          </p>
        ))}
      </div>
    </div>
  )
}
