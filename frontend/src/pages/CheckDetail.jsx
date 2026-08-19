import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { fetchCheck } from '../api/client'
import { normalizeColumns, renderColumnCell } from '../utils/checkColumns'
import { SearchBar, Pagination, LoadingScreen, EmptyState } from '../components/ui'
import LegalNote from '../components/LegalNote'
import { useLang } from '../hooks/useLang'

export default function CheckDetail() {
  const { t, lang, locale } = useLang()
  const { key } = useParams()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState(null)
  const [dir, setDir] = useState('asc')

  const { data, isLoading } = useQuery({
    queryKey: ['check', lang, key, page, search, sort, dir],
    queryFn: () => fetchCheck(key, { page, per_page: 50, search, sort, dir }),
    placeholderData: keepPreviousData,
  })

  const toggleSort = col => {
    if (sort === col) setDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSort(col); setDir('asc') }
    setPage(1)
  }

  if (isLoading) return <LoadingScreen />
  if (!data) return <EmptyState title={t('checkDetail.notFound')} />

  const meta = {
    url_columns: data.url_columns || {},
    cuit_columns: data.cuit_columns || [],
    unit_columns: data.unit_columns || [],
  }
  const columns = normalizeColumns(data.columns || [], meta)

  return (
    <>
      <div className="page-header">
        <div className="breadcrumb">
          <Link to="/">{t('checkDetail.breadcrumb')}</Link>
          <span className="breadcrumb-sep">›</span>
          <span>{data.label}</span>
        </div>
        <h1 className="page-title">{data.label}</h1>
        <p className="page-subtitle">{data.description}</p>
        <LegalNote />
        <div className="flex gap-3 mt-4">
          <span className="badge badge-accent">{t('checkDetail.weightBadge', { value: data.weight })}</span>
          <span className="badge badge-accent">{t('checkDetail.findingsBadge', { count: data.total_findings?.toLocaleString(locale) })}</span>
        </div>
      </div>

      <SearchBar value={search} onChange={v => { setSearch(v); setPage(1) }} placeholder={t('checkDetail.searchPlaceholder')} style={{ marginBottom: 16, maxWidth: 400 }} />

      <div className="card" style={{ overflow: 'hidden' }}>
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                {columns.map(col => (
                  <th key={col.key} className={sort === col.key ? 'sorted' : ''} onClick={() => toggleSort(col.key)}>
                    {col.label}{sort === col.key ? (dir === 'desc' ? ' ↓' : ' ↑') : ''}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(data.items || []).map((row, ri) => (
                <tr key={ri}>
                  {columns.map(col => (
                    <td key={col.key}>
                      {renderColumnCell(col, row, meta)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-between" style={{ padding: '12px 16px', borderTop: '1px solid var(--border)' }}>
          <span className="text-xs text-muted">{t('common.results', { count: (data.total ?? 0).toLocaleString(locale) })}</span>
          <Pagination page={data.page} totalPages={data.total_pages} onPageChange={setPage} />
        </div>
      </div>
    </>
  )
}
