/** Inline SVG icons — stroke matches table accent styling */

const iconProps = { width: 14, height: 14, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true }

export function IconExternal({ size = 14, className = 'cell-icon' }) {
  return (
    <svg {...iconProps} width={size} height={size} className={className}>
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
      <polyline points="15 3 21 3 21 9" />
      <line x1="10" y1="14" x2="21" y2="3" />
    </svg>
  )
}

export function IconEmail({ size = 14, className = 'cell-icon' }) {
  return (
    <svg {...iconProps} width={size} height={size} className={className}>
      <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
      <polyline points="22,6 12,13 2,6" />
    </svg>
  )
}

export function IconPhone({ size = 14, className = 'cell-icon' }) {
  return (
    <svg {...iconProps} width={size} height={size} className={className}>
      <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z" />
    </svg>
  )
}

export function IconAddress({ size = 14, className = 'cell-icon' }) {
  return (
    <svg {...iconProps} width={size} height={size} className={className}>
      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
      <circle cx="12" cy="10" r="3" />
    </svg>
  )
}

export function IconContact({ type, size = 14 }) {
  const key = normalizeContactType(type)
  if (key === 'email') return <IconEmail size={size} />
  if (key === 'phone') return <IconPhone size={size} />
  if (key === 'address') return <IconAddress size={size} />
  return <IconAddress size={size} className="cell-icon cell-icon-muted" />
}

export function normalizeContactType(type) {
  const t = String(type || '').toLowerCase()
  if (t.includes('email')) return 'email'
  if (t.includes('phone')) return 'phone'
  if (t.includes('address')) return 'address'
  return 'other'
}

const US_STAR =
  'M0,-1 L0.29,-0.31 L1,0 L0.29,0.31 L0,1 L-0.29,0.31 L-1,0 L-0.29,-0.31 Z'

function usStarPositions(cantonW, cantonH) {
  const positions = []
  const rows = 9
  for (let row = 0; row < rows; row += 1) {
    const count = row % 2 === 0 ? 6 : 5
    const y = cantonH * 0.12 + row * (cantonH * 0.76 / (rows - 1))
    const xStep = cantonW / 6.2
    const x0 = row % 2 === 1 ? xStep * 0.5 : xStep * 0.15
    for (let col = 0; col < count; col += 1) {
      positions.push([x0 + col * xStep, y])
    }
  }
  return positions
}

export function FlagUS({ size = 20 }) {
  const w = 19
  const h = 10
  const stripeH = h / 13
  const cantonW = w * 0.538
  const cantonH = stripeH * 7
  const displayH = Math.round(size * (h / w))
  const starR = 0.28

  return (
    <svg width={size} height={displayH} viewBox={`0 0 ${w} ${h}`} className="lang-flag" aria-hidden>
      {Array.from({ length: 13 }, (_, i) => (
        <rect
          key={`stripe-${i}`}
          x={0}
          y={i * stripeH}
          width={w}
          height={stripeH}
          fill={i % 2 === 0 ? '#B22234' : '#FFFFFF'}
        />
      ))}
      <rect x={0} y={0} width={cantonW} height={cantonH} fill="#3C3B6E" />
      <g fill="#FFFFFF">
        {usStarPositions(cantonW, cantonH).map(([cx, cy], i) => (
          <path key={i} d={US_STAR} transform={`translate(${cx} ${cy}) scale(${starR})`} />
        ))}
      </g>
    </svg>
  )
}

export function FlagAR({ size = 18 }) {
  return (
    <svg width={size} height={Math.round(size * 0.67)} viewBox="0 0 18 12" className="lang-flag" aria-hidden>
      <rect width="18" height="12" fill="#74acdf" />
      <rect y="4" width="18" height="4" fill="#fff" />
      <circle cx="9" cy="6" r="1.6" fill="#f6b40e" />
    </svg>
  )
}
