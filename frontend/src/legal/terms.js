/*
 * Terms-of-use acceptance, stored per browser. Bump TERMS_VERSION whenever the
 * terms text changes: every visitor is asked to accept again.
 * The old coima.disclaimerDismissed flag does not count as acceptance.
 */
export const TERMS_VERSION = '1.0'
const STORAGE_KEY = 'coima.termsAcceptance'

export function readAcceptance() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const value = JSON.parse(raw)
    return value?.version === TERMS_VERSION ? value : null
  } catch {
    return null
  }
}

// Returns { saved, value }. saved is false when storage is unavailable
// (private mode, blocked site data): the acceptance then lasts this session only.
export function writeAcceptance() {
  const value = { version: TERMS_VERSION, acceptedAt: new Date().toISOString() }
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
    return { saved: true, value }
  } catch {
    return { saved: false, value }
  }
}
