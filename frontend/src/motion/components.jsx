import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { DUR, EASE } from './tokens'
import { fadeIn, enter, finished, play } from './animate'
import { useReveal } from './hooks'

/*
 * Route transition. Fades the page in on every pathname change, resets the
 * scroll and moves focus to <main> so keyboard and screen-reader users start
 * at the new content (main has tabIndex=-1 and no focus ring, see index.css).
 */
export function PageTransition({ children, mainRef }) {
  const { pathname } = useLocation()
  const ref = useRef(null)
  const first = useRef(true)

  useLayoutEffect(() => {
    if (first.current) {
      first.current = false
    } else {
      window.scrollTo(0, 0)
      mainRef?.current?.focus({ preventScroll: true })
    }
    const anim = fadeIn(ref.current, { duration: DUR.page })
    return () => anim?.cancel()
  }, [pathname, mainRef])

  return <div ref={ref}>{children}</div>
}

/*
 * Wraps loaded content whose children carry data-reveal="1..n"; they rise in
 * reading order. Mount it once the data is ready.
 */
export function Reveal({ as: Tag = 'div', children, ...rest }) {
  const ref = useRef(null)
  useReveal(ref)
  return <Tag ref={ref} {...rest}>{children}</Tag>
}

/*
 * A number that crossfades when its value changes. Always shows the real
 * value: no counting up from zero, no fictitious intermediate numbers.
 */
export function AnimatedValue({ value, format = v => String(v), className = '', ...rest }) {
  const ref = useRef(null)
  const prev = useRef(value)

  useLayoutEffect(() => {
    if (prev.current === value) return undefined
    prev.current = value
    const anim = enter(ref.current, { distance: 4, duration: DUR.value })
    return () => anim?.cancel()
  }, [value])

  return (
    <span ref={ref} className={`tabular ${className}`.trim()} {...rest}>
      {format(value)}
    </span>
  )
}

/*
 * Animated expand / collapse (height + opacity). Content unmounts once closed.
 * Base of progressive disclosure across the product.
 */
export function Disclosure({ open, children, id, className = '' }) {
  const ref = useRef(null)
  const [render, setRender] = useState(open)

  useEffect(() => {
    if (open) setRender(true)
  }, [open])

  useLayoutEffect(() => {
    const el = ref.current
    if (!open || !render || !el) return undefined
    el.style.overflow = 'hidden'
    const anim = play(
      el,
      [{ height: '0px', opacity: 0 }, { height: `${el.scrollHeight}px`, opacity: 1 }],
      { duration: DUR.list + 60, easing: EASE.in, fill: 'none' },
    )
    finished(anim).then(() => { el.style.overflow = '' })
    return () => anim?.cancel()
  }, [open, render])

  useEffect(() => {
    const el = ref.current
    if (open || !render) return undefined
    let cancelled = false
    let anim = null
    if (el) {
      el.style.overflow = 'hidden'
      anim = play(
        el,
        [{ height: `${el.scrollHeight}px`, opacity: 1 }, { height: '0px', opacity: 0 }],
        { duration: DUR.modalOut, easing: EASE.out, fill: 'forwards' },
      )
    }
    finished(anim).then(() => { if (!cancelled) setRender(false) })
    return () => { cancelled = true }
  }, [open, render])

  if (!render) return null
  return <div ref={ref} id={id} className={className}>{children}</div>
}
