import { useMemo, useState } from 'react'
import Icon from '../../components/Icon.jsx'

/**
 * The surveillance report (T3.23).
 *
 * `SurveillanceReport.markdown` is a required field of the organiser's own
 * type, not a separate export — it is the "readable by a non-technical
 * reviewer" deliverable, and it arrives already written. So this component
 * renders it rather than re-deriving a second summary from the structured
 * fields, which would give the page and the graded object two different
 * accounts of the same period.
 *
 * A very small Markdown renderer, on purpose: the report's own generator
 * writes headings, bullets, one table and bold runs, and nothing else. Adding
 * a Markdown library to render six constructs would be a dependency carrying
 * a parser for syntax this document never contains.
 *
 * The superseded-findings section is not collapsed by default and is not
 * buried at the bottom of a scroll. PRD FR-4's whole point is that a finding
 * which stopped being true is neither silently dropped nor left looking
 * current, and a section nobody scrolls to is the UI version of dropping it.
 */

function renderInline(text, key) {
  // Bold and inline code only. Anything else the generator does not emit.
  const parts = String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={`${key}-${i}`}>{part.slice(2, -2)}</strong>
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return <code key={`${key}-${i}`} className="t-mono">{part.slice(1, -1)}</code>
    }
    return part
  })
}

function renderMarkdown(md) {
  const lines = String(md || '').split('\n')
  const out = []
  let list = null
  let table = null

  const flush = () => {
    if (list) { out.push(<ul key={`l${out.length}`} className="watch-md-list">{list}</ul>); list = null }
    if (table) {
      const [head, ...body] = table
      out.push(
        <div className="u-scroll" key={`t${out.length}`}>
          <table className="watch-table">
            <thead><tr>{head.map((c, i) => <th key={i}>{renderInline(c, `h${i}`)}</th>)}</tr></thead>
            <tbody>
              {body.map((r, ri) => (
                <tr key={ri}>{r.map((c, ci) => <td key={ci}>{renderInline(c, `c${ri}${ci}`)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>)
      table = null
    }
  }

  lines.forEach((raw, i) => {
    const line = raw.trimEnd()
    if (/^\|[-\s|:]+\|$/.test(line)) return            // the table's rule row
    if (line.startsWith('|')) {
      const cells = line.split('|').slice(1, -1).map((c) => c.trim())
      if (list) flush()
      table = table || []
      table.push(cells)
      return
    }
    if (table) flush()

    if (line.startsWith('### ')) { flush(); out.push(<h4 key={i} className="t-subheading">{renderInline(line.slice(4), i)}</h4>) }
    else if (line.startsWith('## ')) { flush(); out.push(<h3 key={i} className="t-heading-sm watch-md-h">{renderInline(line.slice(3), i)}</h3>) }
    else if (line.startsWith('# ')) { flush(); out.push(<h2 key={i} className="t-heading">{renderInline(line.slice(2), i)}</h2>) }
    else if (/^\s*[-*] /.test(line)) { list = list || []; list.push(<li key={i} className="t-body">{renderInline(line.replace(/^\s*[-*] /, ''), i)}</li>) }
    else if (!line.trim()) { flush() }
    else { flush(); out.push(<p key={i} className="t-body">{renderInline(line, i)}</p>) }
  })
  flush()
  return out
}

export default function SurveillanceReport({ report, onExplain }) {
  const [query, setQuery] = useState('')
  const rendered = useMemo(() => renderMarkdown(report?.markdown), [report?.markdown])

  if (!report) {
    return (
      <div className="card watch-empty">
        <Icon name="document" size={18} />
        <p className="t-body">Run the period to produce the surveillance report.</p>
      </div>
    )
  }

  const decisions = report.decisions || []
  const shown = query
    ? decisions.filter((d) => `${d.id} ${d.code} ${d.usubjid || ''} ${d.site || ''}`
        .toLowerCase().includes(query.toLowerCase()))
    : decisions.slice(0, 12)

  return (
    <div className="watch-report">
      <article className="card card-lined watch-md">{rendered}</article>

      {/* The decision log. Any of these can be asked "why?" and the answer
          comes back out of the trace file, not out of a model. */}
      <section className="watch-log">
        <div className="section-head">
          <h3 className="t-heading-sm">Decision log</h3>
          <label className="field">
            <input className="input" type="search" placeholder="filter by id, code or subject"
                   value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
        </div>
        <p className="run-note">
          {decisions.length} decision(s) were reached this period.
          {query ? ` ${shown.length} match.` : ' Showing the first 12 — filter to find any other.'}
          {' '}Ask any of them why: the answer is read back out of the trace
          written at the moment the decision was made, never regenerated.
        </p>
        <ul className="watch-loglist">
          {shown.map((d) => (
            <li key={d.id} className="watch-logrow">
              <span className={`tag ${d.action === 'APPROVED' ? 'tag-good' : d.action === 'REJECTED' ? 'tag-crit' : 'tag-idle'}`}>
                {d.action}
              </span>
              <span className="watch-logcode">{d.code}</span>
              <span className="t-quiet">{d.usubjid || d.site || 'study-wide'} · cut {d.cut}</span>
              <span className="u-grow" />
              <span className="t-mono t-caption t-quiet">{d.id}</span>
              <button className="btn btn-quiet btn-xs" onClick={() => onExplain(d.id)}>
                <Icon name="search" size={12} /> Why?
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
