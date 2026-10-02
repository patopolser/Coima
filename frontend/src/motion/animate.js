import { DUR, EASE } from './tokens'
import { prefersReducedMotion } from './reducedMotion'

/*
 * Thin wrapper over the Web Animations API. Every movement in the app goes
 * through here so one place enforces the motion policy:
 *   - only transform and opacity (plus height for disclosures) animate;
 *   - with prefers-reduced-motion, nothing animates and callers get null;
 *   - entrances use fill "backwards" so the element is hidden during its delay
 *     but falls back to its normal style afterwards (never stuck invisible).
 */
export function play(el, keyframes, options = {}) {
  if (!el || typeof el.animate !== 'function' || prefersReducedMotion()) return null
  return el.animate(keyframes, { fill: 'backwards', ...options })
}

// Resolves when the animation ends (or immediately when nothing ran).
export function finished(animation) {
  return animation ? animation.finished.then(() => {}, () => {}) : Promise.resolve()
}

export function enter(el, { delay = 0, distance = 8, duration = DUR.page } = {}) {
  return play(
    el,
    [
      { opacity: 0, transform: `translateY(${distance}px)` },
      { opacity: 1, transform: 'none' },
    ],
    { duration, delay, easing: EASE.in },
  )
}

export function fadeIn(el, { delay = 0, duration = DUR.list } = {}) {
  return play(el, [{ opacity: 0 }, { opacity: 1 }], { duration, delay, easing: EASE.in })
}

export function exit(el, { distance = 4, duration = DUR.modalOut } = {}) {
  return play(
    el,
    [
      { opacity: 1, transform: 'none' },
      { opacity: 0, transform: `translateY(${distance}px)` },
    ],
    { duration, easing: EASE.out, fill: 'forwards' },
  )
}

// Modal / popover entrance: a slight scale-up, like glass settling into place.
export function scaleIn(el, { duration = DUR.modalIn, from = 0.98 } = {}) {
  return play(
    el,
    [
      { opacity: 0, transform: `scale(${from})` },
      { opacity: 1, transform: 'none' },
    ],
    { duration, easing: EASE.in },
  )
}

export function scaleOut(el, { duration = DUR.modalOut, to = 0.98 } = {}) {
  return play(
    el,
    [
      { opacity: 1, transform: 'none' },
      { opacity: 0, transform: `scale(${to})` },
    ],
    { duration, easing: EASE.out, fill: 'forwards' },
  )
}

// Staggered entrance for a list of elements, capped so long lists stay quick.
export function stagger(elements, { step = DUR.stagger, max = DUR.staggerMax, ...opts } = {}) {
  return Array.from(elements).map((el, i) =>
    enter(el, { delay: Math.min(i * step, max), ...opts }),
  )
}

// One sweep of light across a glass panel when it opens. The panel must be
// positioned (the .glass class already is).
export function shine(el, { duration = DUR.shine * 3 } = {}) {
  if (!el || prefersReducedMotion() || typeof el.animate !== 'function') return null
  const sheen = document.createElement('span')
  sheen.className = 'glass-sheen-run'
  sheen.setAttribute('aria-hidden', 'true')
  el.appendChild(sheen)
  const anim = sheen.animate(
    [{ transform: 'translateX(-120%)', opacity: 0 }, { opacity: 1, offset: 0.3 }, { transform: 'translateX(320%)', opacity: 0 }],
    { duration, easing: EASE.hover },
  )
  finished(anim).then(() => sheen.remove())
  return anim
}
