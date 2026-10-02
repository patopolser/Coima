import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { fetchScraperStatus, startScraper, stopScraper, rescrapeOpenProcesses, refreshScraperIndicators } from '../api/client'
import { LoadingScreen, ErrorState, Menu, MenuItem, InfoTip } from '../components/ui'
import { useToast } from '../components/ui/Toast'
import { Reveal, AnimatedValue } from '../motion'
import { IconMore, IconRefresh } from '../components/icons'
import { useLang } from '../hooks/useLang'

export default function Scraper() {
  const { t, locale } = useLang()
  const qc = useQueryClient()
  const toast = useToast()
  const [resetProgress, setResetProgress] = useState(false)
  const [batchSize, setBatchSize] = useState('')
  const [rescrapeMonths, setRescrapeMonths] = useState('')

  const { data: status, isLoading, error, refetch } = useQuery({
    queryKey: ['scraper-status'],
    queryFn: fetchScraperStatus,
    refetchInterval: 3000,
  })

  const onDone = () => qc.invalidateQueries({ queryKey: ['scraper-status'] })
  const onError = err => toast(err.detail || err.message)

  const startMut = useMutation({
    mutationFn: () => {
      const parsed = parseInt(batchSize, 10)
      const body = { reset_progress: resetProgress }
      if (Number.isFinite(parsed) && parsed > 0) body.batch_size = parsed
      return startScraper(body)
    },
    onSuccess: onDone,
    onError,
  })
  const stopMut = useMutation({ mutationFn: stopScraper, onSuccess: onDone, onError })
  const rescrapeMut = useMutation({
    mutationFn: () => {
      const parsed = parseInt(rescrapeMonths, 10)
      return rescrapeOpenProcesses(Number.isFinite(parsed) && parsed > 0 ? parsed : undefined)
    },
    onSuccess: onDone,
    onError,
  })
  const refreshMut = useMutation({ mutationFn: refreshScraperIndicators, onSuccess: onDone, onError })

  if (isLoading) return <LoadingScreen />
  if (error && !status) return <ErrorState error={error} onRetry={refetch} />

  const isRunning = !!status?.is_running
  const scraped = status?.processes_scraped_count ?? 0
  const target = status?.last_run_target_count ?? 0
  const run = status?.current_run || null
  const last = status?.last_run || null
  const pct = target > 0 ? Math.min(100, Math.round(((run?.succeeded ?? 0) / target) * 100)) : 0
  const fmt = n => (n ?? 0).toLocaleString(locale)

  return (
    <Reveal>
      <div className="page-head">
        <h1 className="page-title">{t('scraper.title')}</h1>
        <span className="chip"><span className={`status-dot ${isRunning ? 'on' : ''}`} />{isRunning ? t('scraper.running') : t('scraper.idle')}</span>
        {run?.current_process && <span className="chip mono">{run.current_process}</span>}
        <div className="page-head-actions">
          <Menu label={t('scraper.more')} icon={<IconMore size={18} />} triggerClassName="btn btn-secondary btn-icon">
            <div className="menu-section">
              <span className="label">{t('scraper.rescrapeOpen')}</span>
              <div className="row">
                <label className="field">
                  {t('scraper.rescrapeMonths')}
                  <input type="number" min="1" className="input input-sm" style={{ width: 90 }}
                    placeholder={t('scraper.rescrapeMonthsPlaceholder')} value={rescrapeMonths}
                    disabled={isRunning} onChange={e => setRescrapeMonths(e.target.value)} />
                </label>
                <button type="button" className="btn btn-secondary btn-sm" style={{ alignSelf: 'flex-end' }}
                  disabled={isRunning || rescrapeMut.isPending} onClick={() => rescrapeMut.mutate()}>
                  {t('scraper.run')}
                </button>
              </div>
            </div>
            <div className="menu-sep" />
            <MenuItem icon={<IconRefresh />} onClick={() => refreshMut.mutate()}>{t('scraper.refreshIndicators')}</MenuItem>
          </Menu>
          {isRunning ? (
            <button type="button" className="btn btn-danger" disabled={stopMut.isPending} onClick={() => stopMut.mutate()}>
              {t('scraper.stop')}
            </button>
          ) : (
            <button type="button" className="btn btn-primary" disabled={startMut.isPending} onClick={() => startMut.mutate()}>
              {t('scraper.start')}
            </button>
          )}
        </div>
      </div>

      {!isRunning && (
        <div className="list-toolbar" data-reveal="1">
          <label className="field">
            {t('scraper.batchSize')}
            <input type="number" min="1" className="input input-sm" style={{ width: 110 }}
              placeholder={t('scraper.batchSizePlaceholder')} value={batchSize} onChange={e => setBatchSize(e.target.value)} />
          </label>
          <label className="check" style={{ alignSelf: 'flex-end', height: 32 }}>
            <input type="checkbox" checked={resetProgress} onChange={e => setResetProgress(e.target.checked)} />
            {t('scraper.resetProgress')}
          </label>
        </div>
      )}

      <section className="card kpi-band" data-reveal="2" aria-label={t('scraper.summary')}>
        <div className="kpi"><div className="kpi-label">{t('scraper.totalScraped')}</div><AnimatedValue className="kpi-value" value={scraped} format={fmt} /></div>
        <div className="kpi"><div className="kpi-label">{t('scraper.lastRunTarget')}</div><AnimatedValue className="kpi-value" value={target} format={fmt} /></div>
        <div className="kpi"><div className="kpi-label">{t('scraper.succeeded')}</div><AnimatedValue className="kpi-value" value={run?.succeeded ?? 0} format={fmt} /></div>
        <div className="kpi"><div className="kpi-label">{t('scraper.failed')}</div><AnimatedValue className="kpi-value" value={run?.failed ?? 0} format={fmt} /></div>
      </section>

      {isRunning && target > 0 && (
        <section className="card card-pad row" style={{ marginTop: 20 }} aria-label={t('scraper.progress')}>
          <span className="tabular" style={{ fontWeight: 600, minWidth: 44 }}>{pct}%</span>
          <span className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
            <span style={{ width: `${pct}%` }} />
          </span>
          <span className="label tabular">{fmt(run?.succeeded)} / {fmt(target)}</span>
        </section>
      )}

      {last && (
        <section className="card" style={{ marginTop: 20 }} data-reveal="3" aria-labelledby="last-run-title">
          <div className="card-head">
            <h2 id="last-run-title" className="section-title">{t('scraper.lastRun')}</h2>
            {last.finished_at && <span className="chip mono">{last.finished_at.slice(0, 16).replace('T', ' ')}</span>}
            {last.stopped_early && <span className="chip">{t('scraper.stoppedEarly')}</span>}
            {last.error && <InfoTip>{last.error}</InfoTip>}
          </div>
          <div className="kpi-band" style={{ paddingTop: 0 }}>
            <div className="kpi"><div className="kpi-label">{t('scraper.succeeded')}</div><span className="kpi-value tabular" style={{ fontSize: '1.5rem' }}>{fmt(last.succeeded)}</span></div>
            <div className="kpi"><div className="kpi-label">{t('scraper.failed')}</div><span className="kpi-value tabular" style={{ fontSize: '1.5rem' }}>{fmt(last.failed)}</span></div>
            <div className="kpi"><div className="kpi-label">{t('scraper.skipped')}</div><span className="kpi-value tabular" style={{ fontSize: '1.5rem' }}>{fmt(last.skipped)}</span></div>
          </div>
        </section>
      )}
    </Reveal>
  )
}
