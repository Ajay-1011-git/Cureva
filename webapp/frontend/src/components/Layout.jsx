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
        <div className="nav-links">
          <NavLink to="/atlas" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
            Atlas
          </NavLink>
          <NavLink to="/monitor" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
            Monitor
          </NavLink>
          <NavLink to="/watch" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
            Watch
          </NavLink>
        </div>
      </nav>
      <main ref={mainRef} className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
