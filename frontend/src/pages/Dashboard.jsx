import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchDashboardStats, runDetection } from '../api/client'
import { LoadingScreen, EmptyState, ErrorState, RiskBadge, InfoTip, Menu } from '../components/ui'
import { useToast } from '../components/ui/Toast'
import { Reveal, AnimatedValue } from '../motion'
import { IconArrowRight, IconChevronRight, IconMore, IconRefresh } from '../components/icons'
import { formatDay } from '../utils/dates'
import { useLang } from '../hooks/useLang'

// Re-run detection (operational): tucked in the "…" menu, away from the
// reading path.
function RunDetectionMenu() {
  const { t } = useLang()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const rangeInvalid = dateFrom && dateTo && dateFrom > dateTo

  const mutation = useMutation({
    mutationFn: () => runDetection(true, dateFrom, dateTo),
    onSuccess: () => {
      queryClient.invalidateQueries()
      toast(t('dashboard.runSuccess'), { kind: 'success' })
    },
    onError: err => toast(`${t('dashboard.runError')}: ${err.detail || err.message}`),
  })

  return (
    <Menu label={t('dashboard.actions')} icon={<IconMore size={18} />} triggerClassName="btn btn-secondary btn-icon">
      <div className="menu-section">
        <span className="label">{t('dashboard.rerunTitle')}</span>
        <div className="row">
          <label className="field">
            {t('dashboard.dateFrom')}
            <input type="date" className="input input-sm" value={dateFrom} max={dateTo || undefined}
              disabled={mutation.isPending} onChange={e => setDateFrom(e.target.value)} />
          </label>
          <label className="field">
            {t('dashboard.dateTo')}
            <input type="date" className="input input-sm" value={dateTo} min={dateFrom || undefined}
              disabled={mutation.isPending} onChange={e => setDateTo(e.target.value)} />
          </label>
        </div>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          disabled={mutation.isPending || rangeInvalid}
          onClick={() => mutation.mutate()}
        >
          <IconRefresh /> {mutation.isPending ? t('dashboard.running') : t('dashboard.rerun')}
        </button>
      </div>
    </Menu>
  )
}

function TopRisk({ items }) {
  const { t } = useLang()
  return (
    <section className="focus-card" data-reveal="2" aria-labelledby="top-risk-title">
      <div className="card-head on-focus">
        <h2 id="top-risk-title" className="section-title">{t('dashboard.topRisk')}</h2>
        <span className="spacer" />
        <span className="label" style={{ color: 'var(--text-on-focus-2)' }}>{t('dashboard.risk')}</span>
        <InfoTip align="end">{t('risk.caveatLong')}</InfoTip>
      </div>
      {items.length === 0 ? (
        <p className="rank-meta" style={{ padding: '0 22px 22px' }}>{t('common.noData')}</p>
      ) : (
        <ol className="rank-list">
          {items.map((s, i) => (
            <li key={s.cuit}>
              <Link to={`/companies/${s.cuit}`} className="rank-item">
                <span className="rank-num">{i + 1}</span>
                <span className="truncate" style={{ flex: 1 }}>
                  <span className="rank-name truncate" style={{ display: 'block' }}>{s.company || s.cuit}</span>
                  <span className="rank-meta">{t('common.detectorsCount', { count: (s.flags || []).length })}</span>
                </span>
                <RiskBadge score={s.score} />
              </Link>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

export default function Dashboard() {
  const { t, lang, locale } = useLang()
  const { data: stats, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['dashboard-stats', lang],
    queryFn: fetchDashboardStats,
  })

  if (isLoading) return <LoadingScreen />
  if (isError && error?.status !== 404) return <ErrorState error={error} onRetry={refetch} />
  if (!stats) {
    return <EmptyState title={t('dashboard.noDataTitle')} text={t('dashboard.noDataText')} action={<RunDetectionMenu />} />
  }

  const {
    total_entities = 0,
    total_findings = 0,
    tender_count = 0,
    units_scored = 0,
    last_run_at,
    findings_by_vector = [],
    top_entities = [],
  } = stats
  const vectors = findings_by_vector.filter(v => v.count > 0).sort((a, b) => b.count - a.count)
  const maxCount = Math.max(1, ...vectors.map(v => v.count))
  const fmt = n => n.toLocaleString(locale)

  const kpis = [
    { key: 'processes', value: tender_count },
    { key: 'providers', value: total_entities },
    { key: 'units', value: units_scored },
    { key: 'findings', value: total_findings },
  ]

  return (
    <Reveal>
      <div className="page-head">
        <h1 className="page-title">{t('dashboard.title')}</h1>
        {last_run_at && <span className="chip">{t('dashboard.lastRun', { date: formatDay(last_run_at, locale) })}</span>}
        <div className="page-head-actions"><RunDetectionMenu /></div>
      </div>

      <section className="card kpi-band" data-reveal="1" aria-label={t('dashboard.summary')}>
        {kpis.map(k => (
          <div className="kpi" key={k.key}>
            <div className="kpi-label">{t(`dashboard.kpi.${k.key}`)}</div>
            <AnimatedValue className="kpi-value" value={k.value} format={fmt} />
          </div>
        ))}
      </section>

      <div className="dash-grid" style={{ marginTop: 20 }}>
        <TopRisk items={top_entities.slice(0, 5)} />

        <section className="card" data-reveal="3" aria-labelledby="detectors-title">
          <div className="card-head">
            <h2 id="detectors-title" className="section-title">{t('dashboard.detectors')}</h2>
            <span className="count">{vectors.length}</span>
          </div>
          <div className="detector-head">
            <span>{t('dashboard.detector')}</span>
            <span className="row" style={{ gap: 2 }}>
              {t('dashboard.findings')}
              <InfoTip align="end">{t('dashboard.findingsTip')}</InfoTip>
            </span>
          </div>
          {vectors.length === 0 ? (
            <p className="muted" style={{ padding: '0 22px 22px' }}>{t('dashboard.noFindings')}</p>
          ) : (
            <div style={{ paddingBottom: 8 }}>
              {vectors.map(v => (
                <Link key={v.check} to={`/checks/${v.check}`} className="detector-row">
                  <span className="truncate">{v.label}</span>
                  <span className="detector-bar" aria-hidden="true">
                    <span style={{ width: `${(v.count / maxCount) * 100}%` }} />
                  </span>
                  <span className="tabular" style={{ textAlign: 'right', fontWeight: 600 }}>{fmt(v.count)}</span>
                  <IconChevronRight size={14} />
                </Link>
              ))}
            </div>
          )}
        </section>
      </div>

      <div className="dash-foot" data-reveal="4">
        <Link to="/providers" className="btn btn-primary">
          {t('dashboard.allProviders')} <IconArrowRight />
        </Link>
      </div>
    </Reveal>
  )
}
