import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fetchChecks } from '../../api/client'
import { normalizeColumns, renderColumnCell } from '../../utils/checkColumns'
import { useLang } from '../../hooks/useLang'
import { Reveal, Disclosure, enter } from '../../motion'
import { RiskBadge, EmptyState, riskLevel } from '../ui'
import { RiskCaveat } from '../legal'
import { IconArrowLeft, IconArrowRight, IconChevronDown, IconInfo, IconNetwork } from '../icons'

const EVIDENCE_ROWS = 5
const TICKS = [40, 60, 80]

// Dark focal block: level + score, the one-line caveat and the 0-100 scale.
function ScoreBlock({ risk }) {
  const { t } = useLang()
  const score = Math.round(risk.score ?? 0)
  return (
    <div className="focus-card score-block">
      <div className="score-top">
        <RiskBadge score={score} />
        <span>
          <span className="score-value">{score}</span>
          <span className="score-of">/100</span>
        </span>
      </div>
      <div className="score-scale" role="img" aria-label={t('entity.scaleLabel', { score })}>
        <span className="score-scale-fill" style={{ width: `${Math.min(score, 100)}%`, background: `var(--risk-${riskLevel(score)}-bg)` }} />
        {TICKS.map(x => <span key={x} className="score-scale-tick" style={{ left: `${x}%` }} />)}
      </div>
      <RiskCaveat onDark />
    </div>
  )
}

// "How it's computed", on demand: per-detector contribution, synergies, network context.
function Methodology({ risk, labelOf }) {
  const { t } = useLang()
  const b = risk?.evidence_breakdown
  if (!b) return <p className="method-note">{t('entity.noBreakdown')}</p>
  const checks = [...(b.checks || [])].sort((x, y) => (y.contribution ?? 0) - (x.contribution ?? 0))
  const synergies = b.synergies || []
  const f = b.features
  return (
    <div>
      <div className="method-row head">
        <span>{t('entity.detector')}</span>
        <span className="num">{t('entity.findings')}</span>
        <span className="num">{t('entity.weight')}</span>
        <span className="num">{t('entity.contribution')}</span>
      </div>
      {checks.map(c => (
        <div className="method-row" key={c.check}>
          <span className="truncate">{labelOf(c.check)}</span>
          <span className="num">{c.count}</span>
          <span className="num">{c.weight}</span>
          <span className="num" style={{ color: 'var(--text-1)', fontWeight: 600 }}>{Math.round(c.contribution * 10) / 10}</span>
        </div>
      ))}
      {risk.base_score != null && b.multiplier > 1 && (
        <p className="method-note">{t('entity.synergyNote', { base: risk.base_score, multiplier: b.multiplier })}</p>
      )}
      {synergies.map((s, i) => (
        <div className="method-synergy" key={i}>
          <span>{s.label}</span>
          <span className="tabular" style={{ fontWeight: 600 }}>×{s.multiplier}</span>
        </div>
      ))}
      {f && (f.cobid_degree != null || f.cobid_betweenness != null) && (
        <p className="method-note">
          {t('entity.network', { degree: f.cobid_degree ?? '—', betweenness: f.cobid_betweenness ?? '—' })}
        </p>
      )}
    </div>
  )
}

/*
 * Shared profile for providers, contracting units and officials.
 * Reading order: 1 name + score (focus) -> 2 signals by contribution, the first
 * one preselected -> 3 its evidence -> 4 "see all N".
 */
export default function EntityDetail({
  title, meta, back, risk, findings = {}, searchTerm, graphLink, cellOptions,
}) {
  const { t, lang } = useLang()
  const checksQ = useQuery({ queryKey: ['checks', lang], queryFn: fetchChecks })
  const checkMeta = useMemo(() => {
    const m = {}
    ;(checksQ.data || []).forEach(c => { m[c.key] = c })
    return m
  }, [checksQ.data])
  const labelOf = key => checkMeta[key]?.label || key.replace(/_/g, ' ')

  // Signals ordered by their contribution to the score (fallback: count).
  const signals = useMemo(() => {
    const contrib = {}
    ;(risk?.evidence_breakdown?.checks || []).forEach(c => { contrib[c.check] = c.contribution ?? 0 })
    return Object.entries(findings)
      .filter(([, rows]) => rows?.length)
      .map(([key, rows]) => ({ key, rows, contribution: contrib[key] }))
      .sort((a, b) => (b.contribution ?? -1) - (a.contribution ?? -1) || b.rows.length - a.rows.length)
  }, [findings, risk])
  const maxContribution = Math.max(1, ...signals.map(s => s.contribution ?? 0))

  const [selectedKey, setSelectedKey] = useState(null)
  const selected = signals.find(s => s.key === selectedKey) || signals[0]
  const [showMethod, setShowMethod] = useState(false)

  // Selection indicator glides to the selected signal; evidence crossfades.
  const listRef = useRef(null)
  const evidenceRef = useRef(null)
  const [indicator, setIndicator] = useState(null)
  const firstPaint = useRef(true)
  useLayoutEffect(() => {
    const el = listRef.current?.querySelector('[aria-selected="true"]')
    if (el) setIndicator({ top: el.offsetTop + 10, height: el.offsetHeight - 20 })
    if (firstPaint.current) { firstPaint.current = false; return undefined }
    const anim = enter(evidenceRef.current, { distance: 4, duration: 180 })
    return () => anim?.cancel()
  }, [selected?.key])

  const meta2 = selected ? checkMeta[selected.key] || {} : {}
  const cols = selected ? normalizeColumns(meta2.columns || [], meta2) : []

  return (
    <Reveal>
      {back && (
        <Link to={back.to} className="back-link"><IconArrowLeft size={14} /> {back.label}</Link>
      )}

      <section className="card entity-head" data-reveal="1">
        <div style={{ minWidth: 0 }}>
          <h1 className="entity-name">{title}</h1>
          {meta && <div className="entity-meta">{meta}</div>}
          <div className="entity-actions">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              aria-expanded={showMethod}
              aria-controls="methodology"
              onClick={() => setShowMethod(v => !v)}
            >
              <IconInfo /> {t('entity.howComputed')}
              <IconChevronDown size={14} style={{ transform: showMethod ? 'rotate(180deg)' : 'none', transition: 'transform var(--dur-hover) var(--ease-in)' }} />
            </button>
            {graphLink && (
              <Link to={graphLink} className="btn btn-ghost btn-sm"><IconNetwork /> {t('entity.viewNetwork')}</Link>
            )}
          </div>
        </div>
        {risk && <div className="entity-side"><ScoreBlock risk={risk} /></div>}
        <div style={{ gridColumn: '1 / -1' }}>
          <Disclosure open={showMethod} id="methodology">
            <div style={{ paddingTop: 18 }}><Methodology risk={risk} labelOf={labelOf} /></div>
          </Disclosure>
        </div>
      </section>

      {signals.length === 0 ? (
        <div className="card" data-reveal="2">
          <EmptyState title={t('entity.noSignalsTitle')} text={t('entity.noSignalsText')} />
        </div>
      ) : (
        <section className="card signals">
          <div className="signals-list" role="tablist" aria-orientation="vertical" aria-label={t('entity.signals')} ref={listRef} data-reveal="2" style={{ position: 'relative' }}>
            <h2 className="section-title">{t('entity.signalsCount', { count: signals.length })}</h2>
            {signals.map(s => (
              <button
                key={s.key}
                type="button"
                role="tab"
                id={`signal-${s.key}`}
                aria-selected={selected?.key === s.key}
                aria-controls="evidence-panel"
                className="signal"
                onClick={() => setSelectedKey(s.key)}
              >
                <div className="signal-name">{labelOf(s.key)}</div>
                <div className="signal-text">{t('entity.signalFindings', { count: s.rows.length })}</div>
                {s.contribution != null && (
                  <div className="signal-weight">
                    <span className="detector-bar" aria-hidden="true">
                      <span style={{ width: `${(s.contribution / maxContribution) * 100}%`, background: 'var(--accent)' }} />
                    </span>
                    <span>{t('entity.points', { value: Math.round(s.contribution) })}</span>
                  </div>
                )}
              </button>
            ))}
            {indicator && (
              <span className="signal-indicator" aria-hidden="true" style={{ top: 0, transform: `translateY(${indicator.top}px)`, height: indicator.height }} />
            )}
          </div>

          <div className="evidence" id="evidence-panel" role="tabpanel" aria-labelledby={selected ? `signal-${selected.key}` : undefined}>
            <div ref={evidenceRef} data-reveal="3" style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0 }}>
              <div className="evidence-head">
                <h2 className="evidence-title">
                  <span>{t('entity.evidence')}: </span>{labelOf(selected.key)}
                </h2>
              </div>
              <div className="table-wrap">
                <table className="table">
                  <thead><tr>{cols.map(col => <th key={col.key}>{col.label}</th>)}</tr></thead>
                  <tbody>
                    {selected.rows.slice(0, EVIDENCE_ROWS).map((row, ri) => (
                      <tr key={ri}>
                        {cols.map(col => <td key={col.key}>{renderColumnCell(col, row, meta2, cellOptions)}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="evidence-foot" data-reveal="4">
              <Link
                to={`/checks/${selected.key}${searchTerm ? `?search=${encodeURIComponent(searchTerm)}` : ''}`}
                className="btn btn-primary"
              >
                {t('entity.viewAll', { count: selected.rows.length })} <IconArrowRight />
              </Link>
            </div>
          </div>
        </section>
      )}
    </Reveal>
  )
}
