import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchDashboardStats, runDetection } from '../api/client'
import { LoadingScreen, EmptyState } from '../components/ui'
import LegalNote from '../components/LegalNote'
import { useLang } from '../hooks/useLang'

const ACCENT_COLORS = ['#6366f1', '#818cf8', '#a5b4fc', '#22d3ee', '#67e8f9']

export default function Dashboard() {
  const navigate = useNavigate()
  const { t, lang, locale } = useLang()
  const queryClient = useQueryClient()
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const { data: stats, isLoading, isError } = useQuery({
    queryKey: ['dashboard-stats', lang],
    queryFn: fetchDashboardStats,
  })

  const rangeInvalid = dateFrom && dateTo && dateFrom > dateTo

  const mutation = useMutation({
    mutationFn: (force) => runDetection(force, dateFrom, dateTo),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] }),
  })

  if (isLoading) return <LoadingScreen />
  if (isError || !stats) return <EmptyState title={t('dashboard.noDataTitle')} text={t('dashboard.noDataText')} />

  const {
    total_entities = 0,
    total_findings = 0,
    tender_count = 0,
    units_scored = 0,
    last_run_at,
    findings_by_vector = [],
  } = stats

  return (
    <>
      <div className="page-header" style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 className="page-title">{t('dashboard.title')}</h1>
          <p className="page-subtitle">
            {t('dashboard.subtitle')}
            {last_run_at && (
              <span className="text-mono" style={{ marginLeft: 12 }}>
                · {t('common.lastRun', { date: last_run_at.slice(0, 10) })}
              </span>
            )}
          </p>
          <LegalNote />
          {mutation.isError && (
            <p style={{ color: '#ef4444', fontSize: 13, marginTop: 4 }}>
              {t('dashboard.runError')}: {mutation.error?.message}
            </p>
          )}
          {mutation.isSuccess && (
            <p style={{ color: '#10b981', fontSize: 13, marginTop: 4 }}>
              {t('dashboard.runSuccess')}
            </p>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 12, flexShrink: 0, flexWrap: 'wrap' }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, color: 'var(--text-muted)' }}>
            {t('dashboard.dateFrom')}
            <input
              type="date"
              value={dateFrom}
              max={dateTo || undefined}
              disabled={mutation.isPending}
              onChange={e => setDateFrom(e.target.value)}
              style={{ padding: '5px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-elevated)', color: 'var(--text-primary)', fontSize: 13 }}
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, color: 'var(--text-muted)' }}>
            {t('dashboard.dateTo')}
            <input
              type="date"
              value={dateTo}
              min={dateFrom || undefined}
              disabled={mutation.isPending}
              onChange={e => setDateTo(e.target.value)}
              style={{ padding: '5px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-elevated)', color: 'var(--text-primary)', fontSize: 13 }}
            />
          </label>
          {(dateFrom || dateTo) && (
            <button
              onClick={() => { setDateFrom(''); setDateTo('') }}
              disabled={mutation.isPending}
              className="btn btn-ghost btn-sm"
              style={{ fontSize: 12 }}
            >
              {t('dashboard.clearRange')}
            </button>
          )}
          <button
            onClick={() => mutation.mutate(true)}
            disabled={mutation.isPending || rangeInvalid}
            className="btn btn-primary"
            style={{ fontSize: 13, opacity: (mutation.isPending || rangeInvalid) ? 0.6 : 1, cursor: (mutation.isPending || rangeInvalid) ? 'not-allowed' : 'pointer' }}
          >
            {mutation.isPending ? t('dashboard.running') : t('dashboard.runDetectionForce')}
          </button>
        </div>
      </div>

      <div className="grid grid-4 mb-8">
        <div className="card kpi-card card-glow">
          <div className="kpi-label">{t('dashboard.providersScored')}</div>
          <div className="kpi-value">{total_entities.toLocaleString(locale)}</div>
        </div>
        <div className="card kpi-card card-glow">
          <div className="kpi-label">{t('dashboard.totalFindings')}</div>
          <div className="kpi-value">{total_findings.toLocaleString(locale)}</div>
        </div>
        <div className="card kpi-card card-glow">
          <div className="kpi-label">{t('dashboard.processesAnalyzed')}</div>
          <div className="kpi-value">{tender_count.toLocaleString(locale)}</div>
        </div>
        <div className="card kpi-card card-glow">
          <div className="kpi-label">{t('dashboard.unitsScored')}</div>
          <div className="kpi-value">{units_scored.toLocaleString(locale)}</div>
        </div>
      </div>

      <div className="kpi-label mb-4">{t('dashboard.exploreVectors')}</div>
      <div className="grid grid-3" style={{ gap: 12 }}>
        {findings_by_vector.filter(v => v.count > 0).map((v, i) => (
          <div key={v.check} className="card card-body card-glow"
            onClick={() => navigate(`/checks/${v.check}`)}
            style={{ cursor: 'pointer', transition: 'all 0.2s var(--ease)' }}>
            <div className="flex items-center gap-2 mb-2">
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: ACCENT_COLORS[i % ACCENT_COLORS.length] }} />
              <span className="font-semibold text-sm" style={{ color: 'var(--text-primary)' }}>{v.label}</span>
            </div>
            <div className="flex items-center justify-between mt-2">
              <span className="text-xs uppercase text-muted">
                <span style={{ color: 'var(--text-primary)', fontWeight: 700 }}>{v.count.toLocaleString(locale)}</span> {t('dashboard.findingsLabel')}
              </span>
              <span className="text-xs text-muted">{t('dashboard.weightLabel')}: <span style={{ color: 'var(--accent-glow)' }}>{v.weight}</span></span>
            </div>
          </div>
        ))}
      </div>
    </>
  )
}
