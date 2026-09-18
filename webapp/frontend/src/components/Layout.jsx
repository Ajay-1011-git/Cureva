import { useRef, useEffect } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import gsap from 'gsap'

/**
 * Shared nav bar + GSAP page-enter transition (T1.30). Infrastructure, not
 * the showcase animation itself — a simple fade+slight-slide on route change,
 * confirmed to visibly run below.
 */
export default function Layout() {
  const mainRef = useRef(null)
  const location = useLocation()

  useEffect(() => {
    if (!mainRef.current) return
    gsap.fromTo(
      mainRef.current,
      { opacity: 0, y: 16 },
      { opacity: 1, y: 0, duration: 0.45, ease: 'power2.out' }
    )
  }, [location.pathname])

  return (
    <div className="app-shell">
      <nav className="nav-bar">
        <div className="nav-brand">Cureva <span className="nav-brand-sub">Study Sentinel</span></div>
        {/* Only Atlas is navigable while Stage 1 is the whole product. The
            /monitor and /watch routes still resolve (so a deep link doesn't
            404) but are not advertised until Stage 2/3 exist and have
            something real behind them. */}
        <div className="nav-links">
          <NavLink to="/atlas" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
            Atlas
          </NavLink>
        </div>
      </nav>
      <main ref={mainRef} className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
