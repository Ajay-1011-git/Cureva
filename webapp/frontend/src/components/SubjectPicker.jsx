import { useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import Icon from './Icon.jsx'

/**
 * Chooses which enrolled subject the avatar is speaking to.
 *
 * Replaces a free-text id field, which required knowing a USUBJID by heart and
 * silently accepted typos as "a subject with no records". This lists the real
 * enrolled subjects with enough context to pick one deliberately — site, arm,
 * demographics, how many findings already stand against them, and how many
 * things they have said in earlier conversations.
 *
 * The menu is animated with framer-motion rather than GSAP: it needs a real
 * *exit* animation, and presence-on-unmount is the one thing GSAP cannot do
 * for a React-owned subtree without keeping the node mounted by hand.
 */
export default function SubjectPicker({ subjects, value, onChange, disabled }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const rootRef = useRef(null)

  useEffect(() => {
    const onDocClick = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false)
    }
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
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
    <div className="picker" ref={rootRef}>
      <button
        type="button"
        className="picker-trigger"
        onClick={() => setOpen((o) => !o)}
        disabled={disabled}
        aria-expanded={open}
        aria-haspopup="listbox"
        data-testid="subject-trigger"
      >
        <span className="picker-id">{value}</span>
        {current && (
          <span className="picker-meta">
            {current.site} · {current.arm} · {current.age}{current.sex}
            {current.findings > 0 && (
              <span className="tag tag-warn" style={{ padding: '2px 9px' }}>
                {current.findings} finding{current.findings > 1 ? 's' : ''}
              </span>
            )}
          </span>
        )}
        <span className="picker-caret"><Icon name="chevron" size={14} /></span>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            className="picker-menu"
            data-testid="subject-menu"
            role="listbox"
            initial={{ opacity: 0, y: -8, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className="picker-search">
              <Icon name="search" size={15} />
              <input
                autoFocus
                className="input"
                placeholder="Filter by id, site, arm, country…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>

            <div className="picker-count">
              {filtered.length} of {subjects.length} subjects
            </div>

            <ul className="picker-list u-scroll">
              {filtered.map((s) => (
                <li key={s.usubjid}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={s.usubjid === value}
                    className={`picker-option${s.usubjid === value ? ' is-selected' : ''}`}
                    onClick={() => { onChange(s.usubjid); setOpen(false); setQuery('') }}
                  >
                    <span className="picker-option-id">{s.usubjid}</span>
                    <span className="picker-option-meta">
                      {s.site} · {s.arm} · {s.age}{s.sex} · {s.country}
                    </span>
                    <span className="picker-option-tags">
                      {s.findings > 0 && (
                        <span className="tag tag-warn" style={{ padding: '2px 9px' }}>{s.findings}</span>
                      )}
                      {s.pro_records > 0 && (
                        <span className="tag tag-quiet" style={{ padding: '2px 9px' }}>
                          {s.pro_records} said
                        </span>
                      )}
                    </span>
                  </button>
                </li>
              ))}
              {filtered.length === 0 && (
                <li className="picker-empty">No subject matches “{query}”.</li>
              )}
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
