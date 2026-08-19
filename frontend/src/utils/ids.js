/*
 * URL-safe encoding for entity identifiers that may contain characters which
 * break React Router path segments — most notably the "/" in UOC codes
 * (e.g. "424/0"). We base64url-encode the id into a single opaque segment, so
 * routes stay as `/units/:code` and work identically in dev, production and
 * behind any SPA fallback (no multi-segment paths, no encoded-slash quirks).
 *
 * encodeId("424/0")  -> "NDI0LzA"   (used in links/navigation)
 * decodeId("NDI0LzA") -> "424/0"    (used in the detail page to recover the id)
 */

// UTF-8 safe base64 (handles accents etc.), then made URL-safe.
export function encodeId(value) {
  const s = String(value ?? '')
  const b64 = btoa(unescape(encodeURIComponent(s)))
  return b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

export function decodeId(token) {
  if (token == null) return ''
  let s = String(token).replace(/-/g, '+').replace(/_/g, '/')
  while (s.length % 4) s += '='
  try {
    return decodeURIComponent(escape(atob(s)))
  } catch {
    // Not a valid token (e.g. a raw code from an old link) — return as-is.
    return String(token)
  }
}
