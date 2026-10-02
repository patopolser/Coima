// "2026-09-30T08:40:00" -> "30 sep 2026" (es-AR) / "Sep 30, 2026" (en-US).
export function formatDay(value, locale = 'en-US') {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value).slice(0, 10)
  return d.toLocaleDateString(locale, { day: 'numeric', month: 'short', year: 'numeric' })
}
