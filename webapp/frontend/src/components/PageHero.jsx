import { useRef } from 'react'
import Icon from './Icon.jsx'
import { gsap, useGsap, reducedMotion, armFailsafe } from '../lib/motion.js'

/**
 * The sky band that opens every page.
 *
 * One per page, at the top, never repeated below — the gradient is the
 * system's only atmospheric moment and it means "this is where the page
 * begins". Everything under it is white.
 *
 * The entrance is a word-by-word rise out of the headline's own baseline,
 * which is why the words are wrapped in clipping masks: with a 0.90
 * line-height there is no room for a word to fade in from below without
 * overlapping the line above, so it is masked instead.
 *
 * The masks are rendered by React rather than spliced into the DOM after the
 * fact. Splitting the headline imperatively meant React owned the `<h1>`'s
 * children and reclaimed them on the next render — the spans vanished, the
 * effect then found nothing to animate, and GSAP warned about an empty target
 * while the headline silently stopped animating.
 */
export default function PageHero({ eyebrow, eyebrowIcon = 'pulse', title, sub, children }) {
  const rootRef = useRef(null)

  useGsap((_self, scope) => {
    const words = scope.querySelectorAll('.split-word')
    const eyebrowEl = scope.querySelector('.hero-eyebrow')
    const subEl = scope.querySelector('.hero-sub')
    const actionsEl = scope.querySelector('.hero-actions')
    const blooms = scope.querySelectorAll('.hero-bloom')

    if (reducedMotion()) return

    const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
    // Each target is added only if it exists — `.hero-actions` is absent on a
    // hero with no buttons, and GSAP warns (and skips the rest of the
    // timeline's setup) on a null target.
    if (eyebrowEl) tl.from(eyebrowEl, { opacity: 0, y: 12, duration: 0.5 }, 0)
    if (words.length) tl.from(words, { yPercent: 115, duration: 0.95, stagger: 0.045 }, 0.1)
    if (subEl) tl.from(subEl, { opacity: 0, y: 14, duration: 0.7 }, 0.42)
    if (actionsEl) tl.from(actionsEl, { opacity: 0, y: 14, duration: 0.7 }, 0.54)

    // The headline is the page's first sentence, not an effect. If the intro
    // is starved of frames, show it rather than leaving words clipped inside
    // their masks.
    const disarm = armFailsafe(tl, 3500)

    // The blooms drift forever, on their own timelines, so they never sync up
    // into a single visible pulse.
    blooms.forEach((bloom, i) => {
      gsap.to(bloom, {
        xPercent: i % 2 ? -8 : 10,
        yPercent: i % 2 ? 6 : -7,
        scale: 1.12,
        duration: 16 + i * 5,
        ease: 'sine.inOut',
        repeat: -1,
        yoyo: true,
        delay: i * 1.6,
      })
    })

    return disarm
  }, [title], rootRef)

  // Split on whitespace, keeping the separators, so the rendered headline has
  // exactly the spacing and wrap points the plain string would have had.
  const parts = String(title ?? '').split(/(\s+)/)

  return (
    <header className="hero" ref={rootRef}>
      <div className="hero-bloom hero-bloom-a" />
      <div className="hero-bloom hero-bloom-b" />
      <div className="hero-bloom hero-bloom-c" />

      <div className="hero-inner">
        {eyebrow && (
          <span className="hero-eyebrow">
            <Icon name={eyebrowIcon} size={13} strokeWidth={1.8} />
            {eyebrow}
          </span>
        )}

        <h1 className="hero-title">
          {parts.map((part, i) => (
            part.trim()
              ? (
                <span className="split-mask" key={i}>
                  <span className="split-word">{part}</span>
                </span>
              )
              : part
          ))}
        </h1>

        {sub && <p className="hero-sub">{sub}</p>}
        {children && <div className="hero-actions">{children}</div>}
      </div>
    </header>
  )
}
