import { useMemo, useState } from 'react'
import Icon from '../../components/Icon.jsx'

/**
 * Drafted paperwork (T3.23).
 *
 * The one non-negotiable here is the same rule Stage 2 applied to a
 * Tribunal-backed verdict versus a skipped one: **a template-only draft is
 * never visually indistinguishable from a polished one** (NFR-3). The tag is
 * not a subtle shade — it is a word, next to an icon, in the row header, and
 * it says which of the two produced the text you are reading.
 *
 * The distinction matters because the two documents make different promises. A
 * template draft states only what the decision's own records state. A polished
 * one has been through a language model that was instructed to change prose
 * and not facts, and was then checked — but "checked" is a weaker claim than
 * "never touched", and the reader is entitled to know which one they have.
 */

const KIND_LABEL = {
  IRB_MEMO: 'Memo to the ethics committee',
  SITE_QUERY: 'Query to the site',
  AVATAR_RULE_UPDATE: 'Standing rule for patient interviews',
}
const KIND_ICON = { IRB_MEMO: 'shield', SITE_QUERY: 'send', AVATAR_RULE_UPDATE: 'user' }

export default function Artifacts({ data }) {
  const [kind, setKind] = useState('ALL')
  const [openId, setOpenId] = useState(null)

  const rows = data?.artifacts || []
  const filtered = useMemo(
    () => (kind === 'ALL' ? rows : rows.filter((r) => r.kind === kind)),
    [rows, kind])

  if (!rows.length) {
    return (
      <div className="card watch-empty">
        <Icon name="document" size={18} />
        <p className="t-body">
          No paperwork yet. A document is drafted only once the medical monitor
          has approved a decision, so an unanswered escalation produces nothing
          here — which is the point of a human gate.
        </p>
      </div>
    )
  }

  const polished = data.by_source?.polished || 0
  const templates = data.by_source?.template_only || 0

  return (
    <div className="watch-artifacts">
      <div className="watch-toolbar">
        <div className="watch-sitepicker" role="tablist" aria-label="Document kind">
          {['ALL', 'IRB_MEMO', 'SITE_QUERY', 'AVATAR_RULE_UPDATE'].map((k) => {
            const n = k === 'ALL' ? rows.length : (data.by_kind?.[k] ?? 0)
            if (k !== 'ALL' && !n) return null
            return (
              <button key={k} role="tab" aria-selected={kind === k}
                      className={`watch-sitetab${kind === k ? ' is-on' : ''}`}
                      onClick={() => setKind(k)}>
                {k === 'ALL' ? 'All' : KIND_LABEL[k].split(' ')[0]}
                <span className="watch-sitetab-p">{n}</span>
              </button>
            )
          })}
        </div>
      </div>

      <p className="run-note">
        {templates} of {rows.length} drafted straight from the decision's own
        records, with no language model involved.
        {polished > 0
          ? ` ${polished} were reworded by a model and checked to have changed no fact — they are tagged below.`
          : ' None was sent to a model in this run.'}
        {' '}Every value in every document below is reproduced from a record you
        can look up.
      </p>

      <ul className="watch-doclist">
        {filtered.map((row) => {
          const open = openId === row.decision_id
          return (
            <li key={row.decision_id} className={`watch-doc${open ? ' is-open' : ''}`}>
              <button className="watch-doc-head"
                      onClick={() => setOpenId(open ? null : row.decision_id)}
                      aria-expanded={open}>
                <Icon name={KIND_ICON[row.kind] || 'document'} size={16} />
                <span className="watch-doc-title">
                  {KIND_LABEL[row.kind] || row.kind}
                  <span className="t-quiet"> · {row.code}</span>
                </span>
                <span className="watch-doc-who">
                  {row.usubjid || row.site || 'study-wide'} · cut {row.cut}
                </span>

                {/* The honesty tag. A word, not a shade. */}
                <span className={`tag ${row.source === 'polished' ? 'tag-warn' : 'tag-quiet'}`}>
                  <Icon name={row.source === 'polished' ? 'sparkle' : 'check'} size={11} />
                  {row.source === 'polished' ? 'model-reworded' : 'template only'}
                </span>
                <Icon name="chevron" size={14} />
              </button>

              {open && (
                <div className="watch-doc-body">
                  <pre className="watch-doc-text">{row.text}</pre>
                  <div className="watch-doc-refs">
                    <span className="t-eyebrow">Records this is drafted from</span>
                    <ul>
                      {(row.facts || []).map((fact, i) => (
                        <li key={i} className="t-mono t-body-sm">{fact}</li>
                      ))}
                    </ul>
                    <p className="t-caption t-quiet">
                      {row.source === 'polished'
                        ? 'This text was reworded by a language model. Every number, date and identifier above was checked to be unchanged from the template; the wording is the model\'s, the facts are not.'
                        : 'This is the template, unmodified. No language model has seen it.'}
                    </p>
                  </div>
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
