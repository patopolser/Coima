import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { DUR, EASE } from './tokens'
import { enter, finished, play, scaleIn, scaleOut } from './animate'
import { prefersReducedMotion } from './reducedMotion'

/*
 * Keeps an element mounted until its exit animation finishes.
 *   const { mounted, ref } = usePresence(open)
 *   return mounted && <div ref={ref}>…</div>
 */
export function usePresence(open, { onEnter = scaleIn, onExit = scaleOut } = {}) {
  const ref = useRef(null)
  const [mounted, setMounted] = useState(open)

  useEffect(() => {
    if (open) setMounted(true)
  }, [open])

  useLayoutEffect(() => {
    if (!open || !mounted || !ref.current) return undefined
    const anim = onEnter(ref.current)
    return () => anim?.cancel()
  }, [open, mounted])

  useEffect(() => {
    if (open || !mounted) return undefined
    let cancelled = false
    const anim = ref.current ? onExit(ref.current) : null
    finished(anim).then(() => { if (!cancelled) setMounted(false) })
    return () => { cancelled = true }
  }, [open, mounted])

  return { mounted, ref }
}

/*
 * Reading-order entrance. Descendants marked data-reveal="1".."n" rise in that
 * order, so the animation walks the eye along the intended path. Runs once on
 * mount (mount the content when its data is ready).
 */
export function useReveal(ref, deps = []) {
  useLayoutEffect(() => {
    const root = ref.current
    if (!root) return undefined
    const els = [...root.querySelectorAll('[data-reveal]')]
    const anims = els.map(el => {
      const step = Math.max(1, Number(el.dataset.reveal) || 1)
      return enter(el, { delay: (step - 1) * DUR.section })
    })
    return () => anims.forEach(a => a?.cancel())
  }, deps)
}

/*
 * List motion for rows/items rendered as direct children of `ref` with a
 * data-key attribute:
 *   - items that appear (new keys) enter with a capped stagger, visible ones only;
 *   - items that move (sorting) glide from their old position (FLIP).
 * Pass a signature that changes when the list changes, e.g. keys.join('|').
 */
export function useAnimatedList(ref, signature) {
  const seen = useRef(new Set())
  const tops = useRef(new Map())

  useLayoutEffect(() => {
    const root = ref.current
    if (!root) return undefined
    const children = [...root.children].filter(el => el.dataset.key != null)
    const anims = []
    const viewport = window.innerHeight
    let fresh = 0

    children.forEach(el => {
      const key = el.dataset.key
      const top = el.offsetTop
      if (!seen.current.has(key)) {
        seen.current.add(key)
        if (el.getBoundingClientRect().top < viewport) {
          anims.push(enter(el, {
            delay: Math.min(fresh * DUR.stagger, DUR.staggerMax),
            duration: DUR.list,
            distance: 4,
          }))
          fresh += 1
        }
      } else if (tops.current.has(key)) {
        const dy = tops.current.get(key) - top
        if (Math.abs(dy) > 1) {
          anims.push(play(el, [{ transform: `translateY(${dy}px)` }, { transform: 'none' }], {
            duration: DUR.list,
            easing: EASE.in,
          }))
        }
      }
    })

    tops.current = new Map(children.map(el => [el.dataset.key, el.offsetTop]))
    return () => anims.forEach(a => a?.cancel())
  }, [signature])
}

/*
 * Specular highlight for .glass surfaces: tracks the pointer through the
 * --mx / --my custom properties read by glass.css.
 */
export function useGlassPointer(ref) {
  useEffect(() => {
    const el = ref.current
    if (!el || prefersReducedMotion()) return undefined
    let raf = 0
    const onMove = e => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        const r = el.getBoundingClientRect()
        el.style.setProperty('--mx', `${e.clientX - r.left}px`)
        el.style.setProperty('--my', `${e.clientY - r.top}px`)
      })
    }
    el.addEventListener('pointermove', onMove)
    return () => {
      el.removeEventListener('pointermove', onMove)
      cancelAnimationFrame(raf)
    }
  }, [ref])
}
