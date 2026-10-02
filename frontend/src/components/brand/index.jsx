import { useTranslation } from 'react-i18next'

/*
 * Brand motifs, used sparingly: the folded-mantle mark (logo, favicon), the
 * ring of twelve stars (loader) and the crescent moon (404 only).
 * Gold is decorative.
 */

// Five-point star path centred on (cx, cy).
function starPath(cx, cy, outer, inner = outer * 0.45) {
  const pts = []
  for (let i = 0; i < 10; i += 1) {
    const r = i % 2 === 0 ? outer : inner
    const a = -Math.PI / 2 + (i * Math.PI) / 5
    pts.push(`${(cx + r * Math.cos(a)).toFixed(2)},${(cy + r * Math.sin(a)).toFixed(2)}`)
  }
  return `M${pts.join('L')}Z`
}

// Twelve star positions on a ring, starting at 12 o'clock.
function ring(cx, cy, radius) {
  return Array.from({ length: 12 }, (_, i) => {
    const a = -Math.PI / 2 + (i * Math.PI) / 6
    return [cx + radius * Math.cos(a), cy + radius * Math.sin(a)]
  })
}

function StarRing({ cx, cy, radius, size, className, staggered = false }) {
  return (
    <g className={className} fill="var(--gold)">
      {ring(cx, cy, radius).map(([x, y], i) => (
        <path
          key={i}
          d={starPath(x, y, size)}
          style={staggered ? { animationDelay: `${i * 70}ms` } : undefined}
        />
      ))}
    </g>
  )
}

// Logo mark "Pliegue": two folds of a mantle opening around a light seam.
// Two-tone here; public/favicon.svg is the flat one-ink version.
export function BrandMark({ size = 32, title }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" role={title ? 'img' : undefined} aria-hidden={title ? undefined : true}>
      {title && <title>{title}</title>}
      <path d="M29 4C17 2 7 12 4 28L13 33C10 21 16 10 29 4Z" fill="var(--accent)" />
      <path d="M28 9C19 14 15 23 17 35L35 28C27 25 23 20 28 9Z" fill="var(--celeste-deep)" />
      <path d="M25 13C21 18 19 24 20 31" fill="none" stroke="#fff" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  )
}

export function Wordmark() {
  const { t } = useTranslation()
  return (
    <span className="wordmark">
      <BrandMark size={30} />
      <span className="wordmark-text">{t('brand.name')}</span>
    </span>
  )
}

// Loader: the crown turns slowly and its stars twinkle. With reduced motion it
// stays still and only the label remains.
export function StarLoader({ label }) {
  const { t } = useTranslation()
  return (
    <div className="star-loader" role="status" aria-live="polite">
      <svg width="48" height="48" viewBox="0 0 40 40" aria-hidden="true" className="star-loader-ring">
        <StarRing cx={20} cy={20} radius={15} size={2.1} className="star-loader-stars" staggered />
      </svg>
      <span className="star-loader-label">{label ?? t('common.loading')}</span>
    </div>
  )
}

// 404 motif: a small crescent under the crown of stars.
export function Crescent({ size = 132 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 120 120" aria-hidden="true" className="crescent">
      <StarRing cx={60} cy={60} radius={52} size={3.2} className="crescent-stars" staggered />
      {/* Horns up. The outer <g> floats. */}
      <g className="crescent-moon">
        <g transform="rotate(-90 60 60)">
          <path
            d="M72 34a28 28 0 1 0 6 44 24 24 0 1 1-6-44z"
            fill="var(--celeste)"
            stroke="var(--celeste-deep)"
            strokeWidth="1.5"
          />
        </g>
      </g>
    </svg>
  )
}
