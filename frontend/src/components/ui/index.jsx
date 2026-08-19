/* Shared UI components barrel export */
import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useCheckLabels } from '../../hooks/useCheckLabels'

export function Skeleton({ width = '100%', height = 16, style }) {
  return <div className="skeleton" style={{ width, height, ...style }} />
}

export function EmptyState({ title, text = '' }) {
  const { t } = useTranslation()
  const displayTitle = title ?? t('common.noData')
  return (
    <div className="empty-state">
      <div className="empty-state-icon">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path strokeLinecap="round" strokeLinejoin="round" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
        </svg>
      </div>
      <div className="empty-state-title">{displayTitle}</div>
      {text && <div className="empty-state-text">{text}</div>}
    </div>
  )
}

// Debounced search input. Keeps a local value so typing is always fluid and
// only propagates onChange after `delay` ms of inactivity, avoiding a query
// refetch (and full-page reload) on every keystroke.
export function SearchBar({ value, onChange, placeholder, style, delay = 300 }) {
  const { t } = useTranslation()
  const [local, setLocal] = useState(value ?? '')

  // Sync when the parent resets the value externally (e.g. clearing filters).
  useEffect(() => { setLocal(value ?? '') }, [value])

  // Propagate the local value upward once typing pauses.
  useEffect(() => {
    if (local === value) return
    const id = setTimeout(() => onChange(local), delay)
    return () => clearTimeout(id)
  }, [local, value, delay, onChange])

  return (
    <div className="search-bar" style={style}>
      <svg className="search-bar-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
      </svg>
      <input
        className="input"
        type="text"
        value={local}
        onChange={e => setLocal(e.target.value)}
        placeholder={placeholder ?? t('common.search')}
      />
    </div>
  )
}

export function Pagination({ page, totalPages, onPageChange }) {
  if (totalPages <= 1) return null
  const pages = []
  const start = Math.max(1, page - 2)
  const end = Math.min(totalPages, page + 2)
  for (let i = start; i <= end; i++) pages.push(i)
  return (
    <div className="pagination">
      <button className="pagination-btn" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>←</button>
      {start > 1 && <><button className="pagination-btn" onClick={() => onPageChange(1)}>1</button><span className="text-muted">…</span></>}
      {pages.map(p => (
        <button key={p} className={`pagination-btn ${p === page ? 'active' : ''}`} onClick={() => onPageChange(p)}>{p}</button>
      ))}
      {end < totalPages && <><span className="text-muted">…</span><button className="pagination-btn" onClick={() => onPageChange(totalPages)}>{totalPages}</button></>}
      <button className="pagination-btn" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>→</button>
    </div>
  )
}

export function RiskBadge({ score }) {
  const color = score >= 80 ? 'var(--risk-critical)' : score >= 60 ? 'var(--risk-high)' : score >= 40 ? 'var(--risk-medium)' : 'var(--risk-low)'
  const pct = Math.min(score, 100)
  return (
    <div className="risk-circle">
      <svg viewBox="0 0 36 36">
        <path className="risk-circle-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
        <path className="risk-circle-fill" style={{ stroke: color, strokeDasharray: `${pct}, 100` }} d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
      </svg>
      <div className="risk-circle-value" style={{ color }}>{score}</div>
    </div>
  )
}

export function FlagPill({ flag, onClick, count, label }) {
  const labels = useCheckLabels()
  const text = label || labels[flag] || flag.replace(/_/g, ' ')
  return (
    <span className="flag-pill" onClick={onClick} style={onClick ? { cursor: 'pointer' } : {}}>
      {text}
      {count > 1 ? <span className="flag-pill-count">{count}</span> : null}
    </span>
  )
}

const FLAG_LIST_INITIAL = 4

/**
 * A wrapping row of FlagPills with a collapsed-by-default "show more" toggle so
 * every flagged check is reachable without overflowing the column.
 * items: [{ flag, count }]
 */
export function FlagPillList({ items = [], initial = FLAG_LIST_INITIAL }) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)
  if (!items.length) return '—'
  const visible = expanded ? items : items.slice(0, initial)
  const hidden = items.length - initial
  return (
    <div className="flex gap-2 flex-wrap">
      {visible.map(({ flag, count }) => <FlagPill key={flag} flag={flag} count={count} />)}
      {hidden > 0 && (
        <button
          className="cell-show-more"
          onClick={e => { e.stopPropagation(); setExpanded(v => !v) }}
        >
          {expanded ? t('common.showLess') : t('common.showMore', { count: hidden })}
        </button>
      )}
    </div>
  )
}

export function ConfidenceMeter({ value = 0, max = 5, title }) {
  // Number of independent corroborating vectors. More filled dots = stronger
  // multi-signal corroboration, shown separately from severity (the score).
  const filled = Math.min(value, max)
  const color = value >= 4 ? 'var(--risk-critical)' : value >= 2 ? 'var(--risk-medium)' : 'var(--text-muted)'
  return (
    <span className="flex items-center gap-2" title={title} style={{ whiteSpace: 'nowrap' }}>
      <span className="flex items-center" style={{ gap: 3 }}>
        {Array.from({ length: max }).map((_, i) => (
          <span
            key={i}
            style={{
              width: 6, height: 6, borderRadius: '50%',
              background: i < filled ? color : 'var(--border)',
              display: 'inline-block',
            }}
          />
        ))}
      </span>
      <span className="text-mono text-xs" style={{ color, fontWeight: 600 }}>
        {value > max ? `${max}+` : value}
      </span>
    </span>
  )
}

export function ScoreBar({ score }) {
  const color = score >= 80 ? 'var(--risk-critical)' : score >= 60 ? 'var(--risk-high)' : score >= 40 ? 'var(--risk-medium)' : 'var(--risk-low)'
  return (
    <div className="flex items-center gap-3" style={{ minWidth: 120 }}>
      <span className="text-mono font-semibold" style={{ color, minWidth: 28, textAlign: 'right' }}>{score}</span>
      <div style={{ flex: 1, height: 4, background: 'var(--border)', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ width: `${Math.min(score, 100)}%`, height: '100%', background: color, borderRadius: 2, transition: 'width 0.4s var(--ease)' }} />
      </div>
    </div>
  )
}

export function LoadingScreen() {
  const { t } = useTranslation()
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 80 }}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16 }}>
        <div className="skeleton" style={{ width: 40, height: 40, borderRadius: '50%' }} />
        <span className="text-muted text-sm">{t('common.loading')}</span>
      </div>
    </div>
  )
}
