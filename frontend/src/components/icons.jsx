/** Inline SVG icons. Stroke icons inherit currentColor. */

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

// UI icons (navigation, actions). 16px by default, stroke 1.75.
function Icon({ size = 16, className, children, strokeWidth = 1.75, style }) {
  return (
    <svg {...iconProps} width={size} height={size} strokeWidth={strokeWidth} className={className} style={style}>
      {children}
    </svg>
  )
}

export const IconPanel = p => (
  <Icon {...p}><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></Icon>
)
export const IconBuilding = p => (
  <Icon {...p}><rect x="5" y="3" width="14" height="18" rx="1.5" /><path d="M9 7h1M14 7h1M9 11h1M14 11h1M9 15h1M14 15h1M10 21v-3h4v3" /></Icon>
)
export const IconLandmark = p => (
  <Icon {...p}><path d="M3 21h18M5 21V10M9.5 21V10M14.5 21V10M19 21V10M2 10l10-6 10 6z" /></Icon>
)
export const IconUser = p => (
  <Icon {...p}><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7" /></Icon>
)
export const IconNetwork = p => (
  <Icon {...p}><circle cx="12" cy="5" r="2.5" /><circle cx="5" cy="19" r="2.5" /><circle cx="19" cy="19" r="2.5" /><path d="M10.8 7.2 6.2 16.8M13.2 7.2l4.6 9.6M7.5 19h9" /></Icon>
)
export const IconSearch = p => (
  <Icon {...p}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.6-3.6" /></Icon>
)
export const IconMore = p => (
  <Icon {...p} strokeWidth={2.5}><path d="M5 12h.01M12 12h.01M19 12h.01" /></Icon>
)
export const IconInfo = p => (
  <Icon {...p}><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></Icon>
)
export const IconChevronRight = p => (
  <Icon {...p}><path d="m9 6 6 6-6 6" /></Icon>
)
export const IconChevronDown = p => (
  <Icon {...p}><path d="m6 9 6 6 6-6" /></Icon>
)
export const IconArrowRight = p => (
  <Icon {...p}><path d="M5 12h14M13 6l6 6-6 6" /></Icon>
)
export const IconArrowLeft = p => (
  <Icon {...p}><path d="M19 12H5M11 6l-6 6 6 6" /></Icon>
)
export const IconClose = p => (
  <Icon {...p}><path d="M6 6l12 12M18 6 6 18" /></Icon>
)
export const IconCheck = p => (
  <Icon {...p}><path d="M5 12.5 10 17l9-10" /></Icon>
)
export const IconAlert = p => (
  <Icon {...p}><path d="M12 4 2.5 20h19z" /><path d="M12 10v4M12 17h.01" /></Icon>
)
export const IconRefresh = p => (
  <Icon {...p}><path d="M20 11a8 8 0 0 0-14.3-4.9L4 8M4 4v4h4M4 13a8 8 0 0 0 14.3 4.9L20 16M20 20v-4h-4" /></Icon>
)
export const IconSettings = p => (
  <Icon {...p}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></Icon>
)
export const IconServer = p => (
  <Icon {...p}><rect x="3" y="4" width="18" height="7" rx="1.5" /><rect x="3" y="13" width="18" height="7" rx="1.5" /><path d="M7 7.5h.01M7 16.5h.01" /></Icon>
)
export const IconMenu = p => (
  <Icon {...p}><path d="M4 7h16M4 12h16M4 17h16" /></Icon>
)
export const IconSort = ({ dir, ...p }) => (
  <Icon {...p} size={p.size ?? 12}>{dir === 'asc' ? <path d="m6 15 6-6 6 6" /> : <path d="m6 9 6 6 6-6" />}</Icon>
)
