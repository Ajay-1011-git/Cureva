/**
 * The motion layer.
 *
 * Every animation in the app goes through here so that three things are true
 * everywhere rather than in most places:
 *
 *  1. **An interrupted animation always fails visible.** Every reveal is a
 *     `from()` tween, so the state GSAP records and restores on revert is the
 *     element's *natural* one. A tween killed halfway — which StrictMode's
 *     double-mount does to every one of them in development — leaves the
 *     element fully visible rather than stranded at whatever opacity it had
 *     reached. Nothing here may depend on an animation running to completion
 *     in order for content to be readable.
 *  2. **Nothing flashes before it animates.** `immediateRender` applies the
 *     from-values inside a layout effect, before the browser paints, so there
 *     is no need to pre-hide anything in CSS. That matters: a CSS rule that
 *     hides content until JS un-hides it turns any scripting failure into a
 *     blank page.
 *  3. **"Settled" means finished.** An element is only marked done in
 *     `onComplete`. Marking it when the tween *starts* means a torn-down
 *     animation can never be retried, because the next mount skips it.
 *  4. **Triggers are cleaned up.** Everything is scoped to a `gsap.context`
 *     that reverts on unmount, so a ScrollTrigger never fires against a
 *     detached node.
 */
import { useEffect, useLayoutEffect, useRef } from 'react'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { Flip } from 'gsap/Flip'

gsap.registerPlugin(ScrollTrigger, Flip)

gsap.defaults({ ease: 'power3.out', duration: 0.7 })

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

/** Mark an element as finished, so a later re-run leaves it alone. */
const settle = (nodes) => {
  for (const n of nodes) n.setAttribute?.('data-reveal-done', '')
}

/**
 * Snap an animation to its end if it has not finished by `deadlineMs`.
 *
 * GSAP damps its own clock whenever a frame takes longer than half a second
 * (`lagSmoothing`), which is the right call for a scrubbing timeline and the
 * wrong one here: on a machine struggling to paint two WebGL scenes it can
 * stretch a 0.7s reveal into tens of seconds, and anything the animation was
 * hiding stays hidden for all of it. The motion is decoration; the headline
 * and the cards underneath it are not. Past a generous deadline the content
 * simply arrives.
 *
 * Returns a disposer, so a context that reverts early does not fire it.
 */
export function armFailsafe(animation, deadlineMs, onSettled) {
  const id = setTimeout(() => {
    if (animation.progress() < 1) animation.progress(1)
    onSettled?.()
  }, deadlineMs)
  return () => clearTimeout(id)
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
      gsap.set(nodes, { clearProps: 'opacity,transform,willChange' })
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

    const disposers = []

    for (const members of groups.values()) {
      // from(), not set()+to(): the recorded state is the natural one, so
      // reverting a half-finished tween restores a *visible* element. The
      // set()+to() form records opacity 0 as the baseline and strands the
      // element at whatever value it had reached when it was killed.
      let disarm = null
      const finish = () => {
        disarm?.()
        settle(members)
        gsap.set(members, { clearProps: 'transform,opacity,willChange' })
      }

      const tween = gsap.from(members, {
        opacity: 0, y, duration, stagger,
        ease: 'power3.out',
        immediateRender: true,
        scrollTrigger: { trigger: members[0], start, once: true },
        // Armed only once the tween is actually running, so a group still
        // below the fold is not snapped open before it is ever reached.
        onStart: () => {
          disarm = armFailsafe(
            tween,
            duration * 1000 + stagger * 1000 * members.length + 1500,
            finish)
        },
        onComplete: finish,
      })
      disposers.push(() => disarm?.())
    }

    // Layout settles after fonts and the 3D canvas size themselves; without a
    // refresh the triggers keep the positions measured before that happened.
    ScrollTrigger.refresh()

    return () => { for (const d of disposers) d() }
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

export { gsap, ScrollTrigger, Flip }
