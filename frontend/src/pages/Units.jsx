import { useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { fetchUnits } from '../api/client'
import { SearchBar, Pagination, ScoreBar, LoadingScreen, ConfidenceMeter, FlagPillList } from '../components/ui'
import { encodeId } from '../utils/ids'
import { useLang } from '../hooks/useLang'

export default function Units() {
  const { t, lang, locale } = useLang()
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['units', lang, page, search],
    queryFn: () => fetchUnits({ page, per_page: 50, search }),
    placeholderData: keepPreviousData,
  })

  if (isLoading) return <LoadingScreen />

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">{t('units.title')}</h1>
        <p className="page-subtitle">{t('units.subtitle')}</p>
      </div>

      <SearchBar value={search} onChange={v => { setSearch(v); setPage(1) }} placeholder={t('units.searchPlaceholder')} style={{ marginBottom: 16, maxWidth: 400 }} />

      <div className="card" style={{ overflow: 'hidden' }}>
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>{t('units.unitCode')}</th>
                <th>{t('units.name')}</th>
                <th>{t('units.tenders')}</th>
                <th style={{ minWidth: 140 }}>{t('units.riskScore')}</th>
                <th>{t('units.confidence')}</th>
                <th>{t('units.checks')}</th>
              </tr>
            </thead>
            <tbody>
              {(data?.items || []).map(u => {
                const checks = Object.entries(u.check_counts || {})
                  .filter(([, c]) => c > 0)
                  .map(([flag, count]) => ({ flag, count }))
                return (
                <tr key={u.code} className="clickable" onClick={() => navigate(`/units/${encodeId(u.code)}`)}>
                  <td className="cell-mono truncate" style={{ maxWidth: 160 }} title={u.code}>{u.code}</td>
                  <td className="cell-bold truncate" style={{ maxWidth: 240 }}>{u.name}</td>
                  <td>{u.total_tenders?.toLocaleString(locale)}</td>
                  <td>
                    <div className="flex items-center gap-2">
                      <ScoreBar score={u.risk_score} />
                      {u.has_synergy && <span title="synergy" style={{ color: 'var(--risk-high)' }}>⚡</span>}
                    </div>
                  </td>
                  <td><ConfidenceMeter value={u.confidence || 0} /></td>
                  <td><FlagPillList items={checks} /></td>
                </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-between" style={{ padding: '12px 16px', borderTop: '1px solid var(--border)' }}>
          <span className="text-xs text-muted">{t('common.units', { count: (data?.total ?? 0).toLocaleString(locale) })}</span>
          <Pagination page={data?.page || 1} totalPages={data?.total_pages || 1} onPageChange={setPage} />
        </div>
      </div>
    </>
  )
}
