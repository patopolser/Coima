import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { fetchScraperStatus, startScraper, stopScraper, rescrapeOpenProcesses, refreshScraperIndicators } from '../api/client'
import { LoadingScreen } from '../components/ui'
import { useLang } from '../hooks/useLang'

export default function Scraper() {
  const { t, locale } = useLang()
  const qc = useQueryClient()
  const [resetProgress, setResetProgress] = useState(false)
  const [batchSize, setBatchSize] = useState('')
  const [rescrapeMonths, setRescrapeMonths] = useState('')

  const { data: status, isLoading } = useQuery({
    queryKey: ['scraper-status'],
    queryFn: fetchScraperStatus,
    refetchInterval: 3000,
  })

  const startMut = useMutation({
    mutationFn: () => {
      const parsed = parseInt(batchSize, 10)
      const body = { reset_progress: resetProgress }
      if (Number.isFinite(parsed) && parsed > 0) body.batch_size = parsed
      return startScraper(body)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scraper-status'] }),
  })
  const stopMut = useMutation({
    mutationFn: stopScraper,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scraper-status'] }),
  })
  const rescrapeMut = useMutation({
    mutationFn: () => {
      const parsed = parseInt(rescrapeMonths, 10)
      return rescrapeOpenProcesses(Number.isFinite(parsed) && parsed > 0 ? parsed : undefined)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scraper-status'] }),
  })
  const refreshMut = useMutation({
    mutationFn: refreshScraperIndicators,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scraper-status'] }),
  })

  if (isLoading) return <LoadingScreen />

  const isRunning = !!status?.is_running
  const scraped = status?.processes_scraped_count ?? 0
  const target = status?.last_run_target_count ?? 0
  const run = status?.current_run || null
  const last = status?.last_run || null
  const pct = target > 0 ? Math.min(100, Math.round((run?.succeeded ?? 0) / target * 100)) : 0
  const fmt = (n) => (n ?? 0).toLocaleString(locale)

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">{t('scraper.title')}</h1>
        <p className="page-subtitle">{t('scraper.subtitle')}</p>
      </div>

      {/* Status + controls */}
      <div className="card card-body mb-8">
        <div className="flex items-center justify-between" style={{ flexWrap: 'wrap', gap: 16 }}>
          <div className="flex items-center gap-3">
            <span
              style={{
                width: 10, height: 10, borderRadius: '50%',
                background: isRunning ? '#10b981' : '#7a829e',
                boxShadow: isRunning ? '0 0 8px #10b981' : 'none',
              }}
            />
            <span className="font-semibold" style={{ color: 'var(--text-primary)' }}>
              {isRunning ? t('scraper.running') : t('scraper.idle')}
            </span>
            {run?.current_process && (
              <span className="text-mono text-xs text-muted">· {run.current_process}</span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-muted" style={{ cursor: isRunning ? 'not-allowed' : 'auto' }}>
              {t('scraper.batchSize')}
              <input
                type="number"
                min="1"
                placeholder={t('scraper.batchSizePlaceholder')}
                value={batchSize}
                disabled={isRunning}
                onChange={e => setBatchSize(e.target.value)}
                style={{ width: 90, padding: '4px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-input, transparent)', color: 'var(--text-primary)' }}
              />
            </label>
            <label className="flex items-center gap-2 text-sm text-muted" style={{ cursor: isRunning ? 'not-allowed' : 'pointer' }}>
              <input
                type="checkbox"
                checked={resetProgress}
                disabled={isRunning}
                onChange={e => setResetProgress(e.target.checked)}
              />
              {t('scraper.resetProgress')}
            </label>
            <button
              className="btn btn-primary btn-sm"
              disabled={isRunning || startMut.isPending}
              onClick={() => startMut.mutate()}
            >
              {t('scraper.start')}
            </button>
            <button
              className="btn btn-ghost btn-sm"
              disabled={!isRunning || stopMut.isPending}
              onClick={() => stopMut.mutate()}
            >
              {t('scraper.stop')}
            </button>
            <label className="flex items-center gap-2 text-sm text-muted" style={{ cursor: isRunning ? 'not-allowed' : 'auto' }}>
              {t('scraper.rescrapeMonths')}
              <input
                type="number"
                min="1"
                placeholder={t('scraper.rescrapeMonthsPlaceholder')}
                value={rescrapeMonths}
                disabled={isRunning}
                onChange={e => setRescrapeMonths(e.target.value)}
                style={{ width: 70, padding: '4px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-input, transparent)', color: 'var(--text-primary)' }}
              />
            </label>
            <button
              className="btn btn-ghost btn-sm"
              disabled={isRunning || rescrapeMut.isPending}
              onClick={() => rescrapeMut.mutate()}
              title={t('scraper.rescrapeOpenHint')}
            >
              {t('scraper.rescrapeOpen')}
            </button>
            <button
              className="btn btn-ghost btn-sm"
              disabled={isRunning || refreshMut.isPending}
              onClick={() => refreshMut.mutate()}
            >
              {t('scraper.refreshIndicators')}
            </button>
          </div>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-4 mb-8">
        <div className="card kpi-card card-glow">
          <div className="kpi-label">{t('scraper.totalScraped')}</div>
          <div className="kpi-value">{fmt(scraped)}</div>
        </div>
        <div className="card kpi-card card-glow">
          <div className="kpi-label">{t('scraper.lastRunTarget')}</div>
          <div className="kpi-value">{fmt(target)}</div>
        </div>
        <div className="card kpi-card card-glow">
          <div className="kpi-label">{t('scraper.succeeded')}</div>
          <div className="kpi-value">{fmt(run?.succeeded)}</div>
        </div>
        <div className="card kpi-card card-glow">
          <div className="kpi-label">{t('scraper.failed')}</div>
          <div className="kpi-value">{fmt(run?.failed)}</div>
        </div>
      </div>

      {/* Current-run progress */}
      {isRunning && target > 0 && (
        <div className="card card-body mb-8">
          <div className="kpi-label mb-4">{t('scraper.currentRunProgress')}</div>
          <div className="flex items-center gap-3">
            <span className="text-mono font-semibold" style={{ minWidth: 44 }}>{pct}%</span>
            <div style={{ flex: 1, height: 6, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
              <div style={{ width: `${pct}%`, height: '100%', background: '#10b981', borderRadius: 3, transition: 'width 0.4s var(--ease)' }} />
            </div>
            <span className="text-xs text-muted">{fmt(run?.succeeded)} / {fmt(target)}</span>
          </div>
        </div>
      )}

      {/* Last run summary */}
      {last && (
        <div className="card card-body">
          <div className="kpi-label mb-4">{t('scraper.lastRun')}</div>
          <div className="grid grid-4" style={{ gap: 12 }}>
            <div><span className="text-xs text-muted">{t('scraper.succeeded')}</span><div className="font-semibold">{fmt(last.succeeded)}</div></div>
            <div><span className="text-xs text-muted">{t('scraper.failed')}</span><div className="font-semibold">{fmt(last.failed)}</div></div>
            <div><span className="text-xs text-muted">{t('scraper.skipped')}</span><div className="font-semibold">{fmt(last.skipped)}</div></div>
            <div><span className="text-xs text-muted">{t('scraper.stoppedEarly')}</span><div className="font-semibold">{last.stopped_early ? t('scraper.yes') : t('scraper.no')}</div></div>
          </div>
          {last.finished_at && (
            <div className="text-xs text-muted mt-4 text-mono">{t('scraper.finishedAt')}: {last.finished_at.slice(0, 19).replace('T', ' ')}</div>
          )}
        </div>
      )}
    </>
  )
}
