import Icon from './Icon.jsx'
import { familyOf, labelFor, CODE_BLURB } from '../lib/findingCodes.js'

/**
 * What one node in the finding graph actually is.
 *
 * A dot in a graph is only useful if you can ask it what it represents. This
 * shows the code, the family it belongs to, the subject, which domains the
 * finding was derived from, the exact records cited as evidence, and — for a
 * patient-reported node — every term the person reported with the verbatim
 * quote behind it, because a PRO record without its quote is
 * indistinguishable from a fabricated one.
 */
export default function FindingDetail({ node, onClose, onSelectSubject }) {
  if (!node) {
    return (
      <div className="detail detail-empty">
        <Icon name="layers" size={22} strokeWidth={1.4} />
        Click any node to see what it is, which records it rests on, and what
        the patient said.
      </div>
    )
  }

  const family = familyOf(node.code)
  const isPatient = node.code === 'PATIENT_REPORTED'
  const records = node.evidence || []
  const docs = records.filter((e) => e.domain === 'DOC')
  const rows = records.filter((e) => e.domain !== 'DOC')

  return (
    <div className="detail u-scroll" data-testid="finding-detail">
      <div className="detail-head">
        <div>
          <span className="detail-code">
            <i style={{ background: family.color }} />
            {labelFor(node.code)}
          </span>
          <div className="detail-blurb">
            {family.label} — {CODE_BLURB[node.code] || family.blurb}
          </div>
        </div>
        <button className="ask-icon-btn" onClick={onClose} aria-label="Close">
          <Icon name="close" size={14} />
        </button>
      </div>

      <dl className="detail-grid">
        <dt>Subject</dt>
        <dd>
          {node.usubjid
            ? <button className="btn-link" style={{ fontSize: 12 }}
                      onClick={() => onSelectSubject?.(node.usubjid)}>
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
        <div className="detail-section">
          <h4>What the patient said ({(node.reported || []).length})</h4>
          {(node.reported || []).length === 0
            ? <p className="detail-muted">Nothing recorded yet.</p>
            : (node.reported || []).map((r, i) => (
                <div key={i} className="detail-quote">
                  <span className={`chip ${r.pro_type === 'CONMED_MENTION' ? 'chip-conmed' : 'chip-symptom'}`}>
                    <Icon name={r.pro_type === 'CONMED_MENTION' ? 'document' : 'pulse'} size={11} />
                    {r.term}
                  </span>
                  <q>{r.quote}</q>
                </div>
              ))}
        </div>
      )}

      <div className="detail-section">
        <h4>Evidence ({records.length})</h4>
        {rows.length === 0 && docs.length === 0 && (
          <p className="detail-muted">No records cited.</p>
        )}
        {rows.length > 0 && (
          <ul className="ref-list">
            {rows.map((e, i) => (
              <li key={i} className="ref">{e.domain}:{e.usubjid}:{e.seq}</li>
            ))}
          </ul>
        )}
        {docs.length > 0 && (
          <ul className="ref-list" style={{ marginTop: rows.length ? 6 : 0 }}>
            {docs.map((e, i) => (
              <li key={i} className="ref ref-doc">{e.document} §{e.section}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
