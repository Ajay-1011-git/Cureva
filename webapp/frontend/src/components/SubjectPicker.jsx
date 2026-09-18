import { useEffect, useMemo, useRef, useState } from 'react'

/**
 * Chooses which enrolled subject the avatar is speaking to.
 *
 * Replaces a free-text id field, which required knowing a USUBJID by heart and
 * silently accepted typos as "a subject with no records". This lists the real
 * enrolled subjects with enough context to pick one deliberately — site, arm,
 * demographics, how many findings already stand against them, and how many
 * things they have said in earlier conversations.
 */
export default function SubjectPicker({ subjects, value, onChange, disabled }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const rootRef = useRef(null)

  useEffect(() => {
    const onDocClick = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return subjects
    return subjects.filter((s) =>
      s.usubjid.toLowerCase().includes(q)
      || (s.site || '').toLowerCase().includes(q)
      || (s.arm || '').toLowerCase().includes(q)
      || (s.country || '').toLowerCase().includes(q))
  }, [subjects, query])

  const current = subjects.find((s) => s.usubjid === value)

  return (
    <div className="subject-picker" ref={rootRef}>
      <button
        type="button"
        className="subject-trigger"
        onClick={() => setOpen((o) => !o)}
        disabled={disabled}
        data-testid="subject-trigger"
      >
        <span className="subject-id">{value}</span>
        {current && (
          <span className="subject-meta">
            {current.site} · {current.arm} · {current.age}{current.sex}
            {current.findings > 0 && (
              <span className="subject-flag">{current.findings} finding{current.findings > 1 ? 's' : ''}</span>
            )}
          </span>
        )}
        <span className="subject-caret">▾</span>
      </button>

      {open && (
        <div className="subject-menu" data-testid="subject-menu">
          <input
            autoFocus
            className="subject-search"
            placeholder="Filter by id, site, arm, country…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="subject-count">
            {filtered.length} of {subjects.length} subjects
          </div>
          <ul className="subject-list">
            {filtered.map((s) => (
              <li key={s.usubjid}>
                <button
                  type="button"
                  className={`subject-option${s.usubjid === value ? ' selected' : ''}`}
                  onClick={() => { onChange(s.usubjid); setOpen(false); setQuery('') }}
                >
                  <span className="subject-option-id">{s.usubjid}</span>
                  <span className="subject-option-meta">
                    {s.site} · {s.arm} · {s.age}{s.sex} · {s.country}
                  </span>
                  <span className="subject-option-tags">
                    {s.findings > 0 && <em className="tag-finding">{s.findings}</em>}
                    {s.pro_records > 0 && <em className="tag-pro">{s.pro_records} said</em>}
                  </span>
                </button>
              </li>
            ))}
            {filtered.length === 0 && (
              <li className="subject-empty">No subject matches “{query}”.</li>
            )}
          </ul>
        </div>
      )}
    </div>
  )
}
