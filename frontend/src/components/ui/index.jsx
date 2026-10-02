/* Shared UI primitives */
import { useState, useEffect, useRef, useId } from 'react'
import { useTranslation } from 'react-i18next'
import { usePresence, useGlassPointer } from '../../motion'
import { StarLoader } from '../brand'
import { IconSearch, IconInfo, IconAlert, IconRefresh, IconChevronRight } from '../icons'

// ── Risk ────────────────────────────────────────────────────────
// Cut-offs shared by every score in the app: <40 low, 40-59 medium,
// 60-79 high, >=80 critical.
export function riskLevel(score = 0) {
  if (score >= 80) return 'critical'
  if (score >= 60) return 'high'
  if (score >= 40) return 'medium'
  return 'low'
}

// Level in words + score. Never show one without the other.
export function RiskBadge({ score = 0 }) {
  const { t } = useTranslation()
  const level = riskLevel(score)
  return (
    <span className={`risk risk-${level}`} title={t('risk.caveat')}>
      {t(`risk.${level}`)} {Math.round(score)}
    </span>
  )
}

export function ScoreBar({ score = 0 }) {
  const level = riskLevel(score)
  return (
    <span className="score-bar">
      <RiskBadge score={score} />
      <span className="score-bar-track" style={{ color: `var(--risk-${level})` }} aria-hidden="true">
        <span className="score-bar-fill" style={{ width: `${Math.min(score, 100)}%` }} />
      </span>
    </span>
  )
}

// Number of independent detectors behind a score, in neutral text: it is
// corroboration, not a probability of guilt.
export function SignalCount({ value = 0 }) {
  const { t } = useTranslation()
  return <span className="secondary tabular">{t('common.detectorsCount', { count: value })}</span>
}

// ── States ──────────────────────────────────────────────────────
export function Skeleton({ width = '100%', height = 16, style }) {
  return <div className="skeleton" style={{ width, height, ...style }} />
}

export function LoadingScreen() {
  return <StarLoader />
}

export function EmptyState({ title, text = '', action }) {
  const { t } = useTranslation()
  return (
    <div className="state">
      <div className="state-icon">
        <IconSearch size={22} />
      </div>
      <div className="state-title">{title ?? t('common.noData')}</div>
      {text && <div className="state-text">{text}</div>}
      {action}
    </div>
  )
}

// Network or server failure, distinct from "not found".
export function ErrorState({ error, onRetry }) {
  const { t } = useTranslation()
  return (
    <div className="state" role="alert">
      <div className="state-icon"><IconAlert size={22} /></div>
      <div className="state-title">{t('errors.title')}</div>
      <div className="state-text">{error?.detail || t('errors.text')}</div>
      {onRetry && (
        <button type="button" className="btn btn-secondary" onClick={onRetry}>
          <IconRefresh /> {t('errors.retry')}
        </button>
      )}
    </div>
  )
}

// Renders the right state for a failed query: 404 -> not found, else error.
export function QueryState({ error, onRetry, notFoundTitle }) {
  if (error?.status === 404) return <EmptyState title={notFoundTitle} text={error.detail} />
  return <ErrorState error={error} onRetry={onRetry} />
}

// ── Inputs ──────────────────────────────────────────────────────
// Debounced search input. Keeps a local value so typing stays fluid and only
// propagates onChange after `delay` ms of inactivity.
export function SearchBar({ value, onChange, placeholder, style, delay = 300, label, autoFocus = false }) {
  const { t } = useTranslation()
  const [local, setLocal] = useState(value ?? '')

  useEffect(() => { setLocal(value ?? '') }, [value])

  useEffect(() => {
    if (local === value) return undefined
    const id = setTimeout(() => onChange(local), delay)
    return () => clearTimeout(id)
  }, [local, value, delay, onChange])

  return (
    <div className="search-field" style={style}>
      <IconSearch className="search-field-icon" />
      <input
        className="input"
        type="search"
        value={local}
        onChange={e => setLocal(e.target.value)}
        placeholder={placeholder ?? t('common.search')}
        aria-label={label ?? placeholder ?? t('common.search')}
        autoFocus={autoFocus}
      />
    </div>
  )
}

export function Switch({ checked, onChange, label }) {
  return (
    <span className="switch">
      <input type="checkbox" role="switch" checked={checked} onChange={e => onChange(e.target.checked)} aria-label={label} />
      <span className="switch-track" />
      <span className="switch-thumb" />
    </span>
  )
}

export function Pagination({ page, totalPages, onPageChange }) {
  const { t } = useTranslation()
  if (!totalPages || totalPages <= 1) return null
  const pages = []
  const start = Math.max(1, page - 2)
  const end = Math.min(totalPages, page + 2)
  for (let i = start; i <= end; i += 1) pages.push(i)
  return (
    <nav className="pagination" aria-label={t('common.pagination')}>
      <button type="button" className="pagination-btn" disabled={page <= 1} onClick={() => onPageChange(page - 1)} aria-label={t('common.prev')}>
        <IconChevronRight size={14} style={{ transform: 'rotate(180deg)' }} />
      </button>
      {start > 1 && (
        <>
          <button type="button" className="pagination-btn" onClick={() => onPageChange(1)}>1</button>
          <span className="pagination-gap">…</span>
        </>
      )}
      {pages.map(p => (
        <button
          key={p}
          type="button"
          className={`pagination-btn ${p === page ? 'active' : ''}`}
          aria-current={p === page ? 'page' : undefined}
          onClick={() => onPageChange(p)}
        >
          {p}
        </button>
      ))}
      {end < totalPages && (
        <>
          <span className="pagination-gap">…</span>
          <button type="button" className="pagination-btn" onClick={() => onPageChange(totalPages)}>{totalPages}</button>
        </>
      )}
      <button type="button" className="pagination-btn" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)} aria-label={t('common.next')}>
        <IconChevronRight size={14} />
      </button>
    </nav>
  )
}

// Sortable table header cell.
export function SortTh({ col, sort, dir, onSort, children, className = '', style }) {
  const active = sort === col
  return (
    <th
      className={`sortable ${active ? 'sorted' : ''} ${className}`.trim()}
      style={style}
      aria-sort={active ? (dir === 'desc' ? 'descending' : 'ascending') : 'none'}
    >
      <button type="button" className="th-inner" onClick={() => onSort(col)}>
        {children}
        {active && <span aria-hidden="true">{dir === 'desc' ? '↓' : '↑'}</span>}
      </button>
    </th>
  )
}

// ── Popovers ────────────────────────────────────────────────────
// Closes `onClose` on outside pointer-down or Escape while `open`.
function useDismiss(open, onClose, boxRef) {
  useEffect(() => {
    if (!open) return undefined
    const onDown = e => { if (boxRef.current && !boxRef.current.contains(e.target)) onClose() }
    const onKey = e => { if (e.key === 'Escape') onClose() }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, onClose, boxRef])
}

/*
 * (i) button that reveals a short definition. Opens on hover, focus or tap,
 * so nothing essential is hover-only.
 */
export function InfoTip({ children, label, align = 'center' }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const boxRef = useRef(null)
  const id = useId()
  const { mounted, ref } = usePresence(open)
  useDismiss(open, () => setOpen(false), boxRef)

  return (
    <span
      className="tip"
      ref={boxRef}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        className="tip-trigger"
        aria-label={label ?? t('common.moreInfo')}
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        onClick={() => setOpen(o => !o)}
        onFocus={() => setOpen(true)}
        onBlur={e => { if (!boxRef.current?.contains(e.relatedTarget)) setOpen(false) }}
      >
        <IconInfo size={15} />
      </button>
      {mounted && (
        <span
          ref={ref}
          id={id}
          role="tooltip"
          className={`tip-bubble glass glass-strong ${align !== 'center' ? `align-${align}` : ''}`}
        >
          {children}
        </span>
      )}
    </span>
  )
}

/*
 * "…" menu: secondary and operational actions live here so they don't
 * compete with the screen's one primary action.
 */
export function Menu({ label, icon, children, triggerClassName = 'btn btn-ghost btn-icon' }) {
  const [open, setOpen] = useState(false)
  const boxRef = useRef(null)
  const { mounted, ref } = usePresence(open)
  useGlassPointer(ref)
  useDismiss(open, () => setOpen(false), boxRef)

  return (
    <div className="menu" ref={boxRef}>
      <button
        type="button"
        className={triggerClassName}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(o => !o)}
      >
        {icon}
      </button>
      {mounted && (
        <div ref={ref} className="menu-panel glass glass-strong" role="menu" onClick={e => { if (e.target.closest('[data-close]')) setOpen(false) }}>
          {typeof children === 'function' ? children(() => setOpen(false)) : children}
        </div>
      )}
    </div>
  )
}

export function MenuItem({ icon, children, onClick, href, external }) {
  const content = <>{icon}{children}</>
  if (href) {
    return (
      <a className="menu-item" role="menuitem" href={href} data-close {...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}>
        {content}
      </a>
    )
  }
  return <button type="button" className="menu-item" role="menuitem" onClick={onClick} data-close>{content}</button>
}
