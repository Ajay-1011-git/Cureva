/**
 * The motion layer.
 *
 * Every animation in the app goes through here so that three things are true
 * everywhere rather than in most places:
 *
 *  1. **Reduced motion is honoured once.** `gsap.matchMedia` is not enough on
 *     its own, because elements start at opacity 0 to avoid a flash — if the
 *     timeline is skipped they would stay invisible. So the reduced-motion
 *     branch still *sets* the final state, it just does not travel there.
 *  2. **Nothing flashes before it animates.** `[data-reveal]` is hidden by CSS
 *     only while `js-motion-ready` is on the document, which this module sets
 *     synchronously on import. With JS disabled or broken the content is
 *     simply visible, which is the correct failure.
 *  3. **Triggers are cleaned up.** React 19 StrictMode mounts effects twice in
 *     development; a ScrollTrigger that is not reverted on unmount will fire
 *     against a detached node and pin the page at opacity 0.
 */
import { useEffect, useLayoutEffect, useRef } from 'react'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { Flip } from 'gsap/Flip'

gsap.registerPlugin(ScrollTrigger, Flip)

gsap.defaults({ ease: 'power3.out', duration: 0.7 })

// Set synchronously at import time, before the first paint of any component
// that relies on it, so the hide-then-reveal rule is never applied to a page
// that will not get its reveal.
if (typeof document !== 'undefined') {
  document.documentElement.classList.add('js-motion-ready')
}

export const reducedMotion = () =>
  typeof window !== 'undefined'
  && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** `useLayoutEffect` in the browser, `useEffect` on the server — silences the
 *  SSR warning without giving up pre-paint timing where it matters. */
const useIsomorphicLayoutEffect =
  typeof window !== 'undefined' ? useLayoutEffect : useEffect

/**
 * Scope a GSAP context to a ref. Everything created inside `fn` is reverted
 * when the component unmounts or `deps` change — which is what makes this
 * safe under StrictMode's double-mount.
 */
export function useGsap(fn, deps = [], scopeRef = null) {
  const localRef = useRef(null)
  const ref = scopeRef || localRef
  useIsomorphicLayoutEffect(() => {
    if (!ref.current) return
    const ctx = gsap.context((self) => fn(self, ref.current), ref)
    return () => ctx.revert()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return ref
}

/** Mark an element as settled so the CSS hide rule stops applying to it. */
const settle = (nodes) => {
  for (const n of nodes) n.setAttribute?.('data-reveal-done', '')
}

/**
 * Reveal every `[data-reveal]` inside `scope` as it scrolls into view.
 *
 * Elements above the fold play immediately on a small stagger; anything lower
 * waits for its own ScrollTrigger. Grouping is by `data-reveal-group` so a row
 * of cards staggers together instead of each card firing alone.
 */
export function useReveal(deps = [], options = {}) {
  const { y = 22, duration = 0.75, stagger = 0.085, start = 'top 88%' } = options

  return useGsap((_self, scope) => {
    const nodes = gsap.utils.toArray('[data-reveal]', scope)
      .filter((n) => !n.hasAttribute('data-reveal-done'))
    if (!nodes.length) return

    if (reducedMotion()) {
      gsap.set(nodes, { opacity: 1, y: 0, clearProps: 'transform' })
      settle(nodes)
      return
    }

    // Bucket by group so siblings share one timeline and one trigger.
    const groups = new Map()
    for (const node of nodes) {
      const key = node.getAttribute('data-reveal-group') || node
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key).push(node)
    }

    for (const members of groups.values()) {
      gsap.set(members, { opacity: 0, y })
      gsap.to(members, {
        opacity: 1, y: 0, duration, stagger,
        ease: 'power3.out',
        scrollTrigger: { trigger: members[0], start, once: true },
        onStart: () => settle(members),
        onComplete: () => gsap.set(members, { clearProps: 'transform,willChange' }),
      })
    }

    // Layout settles after fonts and the 3D canvas size themselves; without a
    // refresh the triggers keep the positions measured before that happened.
    ScrollTrigger.refresh()
  }, deps)
}

/**
 * Count a number up when it enters view.
 *
 * `format` is hoisted to a module constant rather than defaulted inline: a
 * default arrow is a fresh function identity on every render, which would put
 * a new value in the dependency array each time and restart the count on any
 * unrelated re-render of the parent.
 */
const roundFormat = (n) => String(Math.round(n))

export function useCountUp(value, { duration = 1.1, format = roundFormat } = {}) {
  const ref = useRef(null)
  const numeric = typeof value === 'number' && Number.isFinite(value)

  useIsomorphicLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    if (!numeric) { el.textContent = String(value ?? '—'); return }
    if (reducedMotion() || value === 0) { el.textContent = format(value); return }

    // Paint the start value synchronously, so the tile never shows an empty
    // slot for the frame before the first onUpdate.
    el.textContent = format(0)
    const state = { n: 0 }
    const tween = gsap.to(state, {
      n: value, duration, ease: 'power2.out',
      onUpdate: () => { el.textContent = format(state.n) },
      onComplete: () => { el.textContent = format(value) },
    })
    return () => tween.kill()
  }, [value, numeric, duration, format])

  return ref
}

/**
 * A pointer-following nudge for pill buttons. Deliberately small (6px) — the
 * system's buttons are quiet and a big magnetic pull would read as a toy.
 * Disabled on touch, where there is no hover to respond to.
 */
export function useMagnetic({ strength = 6 } = {}) {
  const ref = useRef(null)

  useIsomorphicLayoutEffect(() => {
    const el = ref.current
    if (!el || reducedMotion()) return
    if (!window.matchMedia?.('(hover: hover) and (pointer: fine)').matches) return

    // Hand transform over to GSAP. The button's own CSS transitions transform
    // for its hover lift, and a CSS transition racing a per-pointermove tween
    // makes the element lag behind the cursor instead of tracking it.
    el.classList.add('is-magnetic')

    const quickX = gsap.quickTo(el, 'x', { duration: 0.4, ease: 'power3.out' })
    const quickY = gsap.quickTo(el, 'y', { duration: 0.4, ease: 'power3.out' })

    const onMove = (e) => {
      const r = el.getBoundingClientRect()
      quickX(((e.clientX - (r.left + r.width / 2)) / (r.width / 2)) * strength)
      quickY(((e.clientY - (r.top + r.height / 2)) / (r.height / 2)) * strength)
    }
    const onLeave = () => { quickX(0); quickY(0) }

    el.addEventListener('pointermove', onMove)
    el.addEventListener('pointerleave', onLeave)
    return () => {
      el.removeEventListener('pointermove', onMove)
      el.removeEventListener('pointerleave', onLeave)
      el.classList.remove('is-magnetic')
      gsap.set(el, { x: 0, y: 0 })
    }
  }, [strength])

  return ref
}

/**
 * Split a line of text into word spans for a staggered rise.
 *
 * Hand-rolled rather than GSAP's SplitText: this only ever needs words (not
 * chars or lines), and doing it here keeps the wrapper markup predictable for
 * the hero's tight 0.90 line-height, where an extra inline-block with the
 * wrong vertical-align visibly shifts the baseline.
 */
export function splitWords(el) {
  if (!el || el.dataset.split === 'done') {
    return Array.from(el?.querySelectorAll('.split-word') || [])
  }
  const words = (el.textContent || '').split(/(\s+)/)
  el.textContent = ''
  const out = []
  for (const word of words) {
    if (!word.trim()) { el.appendChild(document.createTextNode(word)); continue }
    const mask = document.createElement('span')
    mask.className = 'split-mask'
    const inner = document.createElement('span')
    inner.className = 'split-word'
    inner.textContent = word
    mask.appendChild(inner)
    el.appendChild(mask)
    out.push(inner)
  }
  el.dataset.split = 'done'
  return out
}

export { gsap, ScrollTrigger, Flip }
