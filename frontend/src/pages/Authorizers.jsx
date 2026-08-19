import { useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { fetchAuthorizers } from '../api/client'
import { SearchBar, Pagination, ScoreBar, LoadingScreen, ConfidenceMeter, FlagPillList } from '../components/ui'
import { encodeId } from '../utils/ids'
import { useLang } from '../hooks/useLang'

export default function Authorizers() {
  const { t, lang, locale } = useLang()
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['authorizers', lang, page, search],
    queryFn: () => fetchAuthorizers({ page, per_page: 50, search }),
    placeholderData: keepPreviousData,
  })

  if (isLoading) return <LoadingScreen />

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">{t('authorizers.title')}</h1>
        <p className="page-subtitle">{t('authorizers.subtitle')}</p>
      </div>

      <SearchBar value={search} onChange={v => { setSearch(v); setPage(1) }} placeholder={t('authorizers.searchPlaceholder')} style={{ marginBottom: 16, maxWidth: 400 }} />

      <div className="card" style={{ overflow: 'hidden' }}>
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>{t('authorizers.name')}</th>
                <th style={{ minWidth: 140 }}>{t('authorizers.riskScore')}</th>
                <th>{t('authorizers.confidence')}</th>
                <th>{t('authorizers.checks')}</th>
              </tr>
            </thead>
            <tbody>
              {(data?.items || []).map(a => {
                const checks = Object.entries(a.check_counts || {})
                  .filter(([, c]) => c > 0)
                  .map(([flag, count]) => ({ flag, count }))
                return (
                <tr key={a.authorizer} className="clickable" onClick={() => navigate(`/authorizers/${encodeId(a.authorizer)}`)}>
                  <td className="cell-bold truncate" style={{ maxWidth: 320 }}>{a.authorizer}</td>
                  <td>
                    <div className="flex items-center gap-2">
                      <ScoreBar score={a.risk_score} />
                      {a.has_synergy && <span title="synergy" style={{ color: 'var(--risk-high)' }}>⚡</span>}
                    </div>
                  </td>
                  <td><ConfidenceMeter value={a.confidence || 0} /></td>
                  <td><FlagPillList items={checks} /></td>
                </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-between" style={{ padding: '12px 16px', borderTop: '1px solid var(--border)' }}>
          <span className="text-xs text-muted">{t('common.results', { count: (data?.total ?? 0).toLocaleString(locale) })}</span>
          <Pagination page={data?.page || 1} totalPages={data?.total_pages || 1} onPageChange={setPage} />
        </div>
      </div>
    </>
  )
}
