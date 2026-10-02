import { useSyncExternalStore } from 'react'

// One shared matchMedia subscription for the whole app. Reacts to the OS
// setting changing mid-session.
const query =
  typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-reduced-motion: reduce)')
    : null

export function prefersReducedMotion() {
  return !!query?.matches
}

function subscribe(callback) {
  if (!query) return () => {}
  query.addEventListener('change', callback)
  return () => query.removeEventListener('change', callback)
}

export function useReducedMotion() {
  return useSyncExternalStore(subscribe, prefersReducedMotion, () => false)
}
