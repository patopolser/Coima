// Money formatting. Large amounts collapse to a scale letter so tables and
// badges stay scannable: 1_000_000 -> "ARS $1M", 2_450_000_000 -> "ARS $2,5B"
// (es locale) / "ARS $2.5B" (en). Pair the compact form with formatFullMoney
// in a title tooltip so the exact figure stays one hover away.

const SCALES = [
  { div: 1e12, suffix: 'T' },
  { div: 1e9, suffix: 'B' },
  { div: 1e6, suffix: 'M' },
  { div: 1e3, suffix: 'K' },
]

const toNumber = amount => (typeof amount === 'number' ? amount : Number(amount))

export function formatCompactMoney(amount, currency, locale = 'en-US') {
  if (amount === null || amount === undefined || amount === '') return '—'
  const num = toNumber(amount)
  const code = currency || 'ARS'
  if (!Number.isFinite(num)) return `${code} $${amount}`
  const scale = SCALES.find(s => Math.abs(num) >= s.div)
  if (!scale) return `${code} $${num.toLocaleString(locale, { maximumFractionDigits: 2 })}`
  const scaled = num / scale.div
  const digits = Math.abs(scaled) >= 100 ? 0 : 1
  return `${code} $${scaled.toLocaleString(locale, { maximumFractionDigits: digits })}${scale.suffix}`
}

export function formatFullMoney(amount, currency, locale = 'en-US') {
  if (amount === null || amount === undefined || amount === '') return '—'
  const num = toNumber(amount)
  const code = currency || 'ARS'
  if (!Number.isFinite(num)) return `${code} $${amount}`
  return `${code} $${num.toLocaleString(locale, { maximumFractionDigits: 2 })}`
}
