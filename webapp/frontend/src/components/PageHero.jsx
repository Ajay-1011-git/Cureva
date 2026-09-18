import { useRef } from 'react'
import Icon from './Icon.jsx'
import { gsap, useGsap, splitWords, reducedMotion } from '../lib/motion.js'

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
 */
export default function PageHero({ eyebrow, eyebrowIcon = 'pulse', title, sub, children }) {
  const rootRef = useRef(null)
  const titleRef = useRef(null)

  useGsap((_self, scope) => {
    const words = splitWords(titleRef.current)
    const eyebrowEl = scope.querySelector('.hero-eyebrow')
    const subEl = scope.querySelector('.hero-sub')
    const actionsEl = scope.querySelector('.hero-actions')
    const blooms = scope.querySelectorAll('.hero-bloom')
    const rest = [eyebrowEl, subEl, actionsEl].filter(Boolean)

    if (reducedMotion()) {
      gsap.set([...words, ...rest], { opacity: 1, y: 0 })
      return
    }

    const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
    tl.from(eyebrowEl, { opacity: 0, y: 12, duration: 0.5 }, 0)
      .from(words, { yPercent: 115, duration: 0.95, stagger: 0.045 }, 0.1)
      .from(subEl, { opacity: 0, y: 14, duration: 0.7 }, 0.42)
      .from(actionsEl, { opacity: 0, y: 14, duration: 0.7 }, 0.54)

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
  }, [title], rootRef)

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
        <h1 className="hero-title" ref={titleRef}>{title}</h1>
        {sub && <p className="hero-sub">{sub}</p>}
        {children && <div className="hero-actions">{children}</div>}
      </div>
    </header>
  )
}
