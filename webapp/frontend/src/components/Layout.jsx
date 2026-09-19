import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import AskPanel from './AskPanel.jsx'
import Icon, { BrandMark } from './Icon.jsx'
import { gsap, reducedMotion, ScrollTrigger, armFailsafe } from '../lib/motion.js'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

const LINKS = [
  { to: '/atlas',   label: 'Atlas',  icon: 'graph' },
  { to: '/monitor', label: 'Review', icon: 'scales' },
  { to: '/watch',   label: 'Watch',  icon: 'pulse' },
]

/**
 * The shared shell: a sticky white bar, one sliding indicator behind the
 * active link, a dot that reports whether the backend actually answered, and
 * the page-enter transition.
 *
 * The indicator is measured from the live DOM rather than positioned by index,
 * because the two links are different widths and the font loads late enough
 * that a hard-coded width would be wrong on first paint.
 */
export default function Layout() {
  const mainRef = useRef(null)
  const navRef = useRef(null)
  const linksRef = useRef(null)
  const location = useLocation()
  const [health, setHealth] = useState(null)   // null = unknown, then ok/down

  // --- page-enter transition on every route change
  useEffect(() => {
    const el = mainRef.current
    if (!el) return
    if (reducedMotion()) { gsap.set(el, { clearProps: 'opacity,transform' }); return }

    const settle = () => {
      gsap.set(el, { clearProps: 'opacity,transform' })
      ScrollTrigger.refresh()
    }
    const tween = gsap.from(el,
      { opacity: 0, y: 18, duration: 0.55, ease: 'power3.out', onComplete: settle })

    // This one fades the entire page, so it is the animation least allowed to
    // stall: starved of frames it leaves every route looking like it failed to
    // load. Short deadline, because 0.55s is all it should ever need.
    const disarm = armFailsafe(tween, 2000, settle)

    // kill() stops the tween wherever it is — on its own that leaves the page
    // stuck at a partial opacity when StrictMode tears the effect down
    // mid-flight. revert() puts the element back to the state from() recorded.
    return () => { disarm(); tween.revert() }
  }, [location.pathname])

  // --- shadow the bar only once the page has moved under it.
  //     A plain scroll listener rather than a ScrollTrigger: with no trigger
  //     element this is just "has the window scrolled", and ScrollTrigger's
  //     start/end syntax is for positions relative to something.
  useEffect(() => {
    const el = navRef.current
    if (!el) return
    const onScroll = () => el.classList.toggle('is-scrolled', window.scrollY > 8)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  // --- slide the indicator to whichever link is active
  useEffect(() => {
    const wrap = linksRef.current
    if (!wrap) return
    const indicator = wrap.querySelector('.nav-indicator')
    const active = wrap.querySelector('.nav-link.active')
    if (!indicator || !active) return

    const move = () => {
      const a = active.getBoundingClientRect()
      const w = wrap.getBoundingClientRect()
      gsap.to(indicator, {
        x: a.left - w.left, width: a.width, opacity: 1,
        duration: reducedMotion() ? 0 : 0.45, ease: 'power3.out',
      })
    }
    move()
    // Re-measure once the display face has loaded; the pill's width changes
    // when Open Runde replaces the fallback.
    document.fonts?.ready.then(move).catch(() => {})
    window.addEventListener('resize', move)
    return () => window.removeEventListener('resize', move)
  }, [location.pathname])

  // --- is the backend actually there?
  useEffect(() => {
    let live = true
    const ping = () => fetch(`${API_BASE}/api/health`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d) => { if (live) setHealth({ ok: true, nodes: d.graph }) })
      .catch(() => { if (live) setHealth({ ok: false }) })
    ping()
    const id = setInterval(ping, 20000)
    return () => { live = false; clearInterval(id) }
  }, [])

  const statusClass = health == null ? '' : health.ok ? 'is-live' : 'is-down'
  const statusText = health == null
    ? 'connecting…'
    : health.ok
      ? `${health.nodes ?? '—'} findings indexed`
      : 'backend unreachable'

  return (
    <>
      <div className="app-shell">
        <nav className="nav" ref={navRef}>
          <div className="nav-inner">
            <NavLink to="/atlas" className="nav-brand">
              <BrandMark />
              <span className="nav-wordmark">Cureva</span>
              <span className="nav-brand-sub">Study Sentinel</span>
            </NavLink>

            {/* Only shipped surfaces appear here; unknown paths redirect to
                /atlas (App.jsx). */}
            <div className="nav-links" ref={linksRef}>
              <span className="nav-indicator" />
              {LINKS.map((l) => (
                <NavLink key={l.to} to={l.to}
                         className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
                  <Icon name={l.icon} size={15} />
                  {l.label}
                </NavLink>
              ))}
            </div>

            <div className="nav-actions">
              <span className={`nav-status ${statusClass}`} title={`${API_BASE}/api/health`}>
                <i />{statusText}
              </span>
            </div>
          </div>
        </nav>

        <main ref={mainRef} className="page">
          <Outlet />
        </main>
      </div>

      {/* Outside .app-shell on purpose: the panel recedes that element when it
          opens, and a panel inside it would recede itself. */}
      <AskPanel />
    </>
  )
}
