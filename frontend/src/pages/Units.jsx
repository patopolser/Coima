import { useRef, useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { fetchUnits } from '../api/client'
import { SearchBar, Pagination, ScoreBar, SignalCount, LoadingScreen, ErrorState, EmptyState, InfoTip } from '../components/ui'
import { Reveal, useAnimatedList } from '../motion'
import { encodeId } from '../utils/ids'
import { useLang } from '../hooks/useLang'

export default function Units() {
  const { t, lang, locale } = useLang()
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const bodyRef = useRef(null)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['units', lang, page, search],
    queryFn: () => fetchUnits({ page, per_page: 50, search }),
    placeholderData: keepPreviousData,
  })
  const items = data?.items || []
  useAnimatedList(bodyRef, items.map(u => u.code).join('|'))

  if (isLoading) return <LoadingScreen />
  if (error && !data) return <ErrorState error={error} onRetry={refetch} />

  return (
    <Reveal>
      <div className="page-head">
        <h1 className="page-title">{t('units.title')}</h1>
        <span className="chip tabular">{(data?.total ?? 0).toLocaleString(locale)}</span>
      </div>

      <div className="list-toolbar" data-reveal="1">
        <SearchBar value={search} onChange={v => { setSearch(v); setPage(1) }} placeholder={t('units.searchPlaceholder')} />
      </div>

      <section className="card" data-reveal="2" style={{ overflow: 'hidden' }}>
        {items.length === 0 ? (
          <EmptyState title={t('common.noResults')} />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t('units.name')}</th>
                  <th>{t('units.code')}</th>
                  <th className="num">{t('units.tenders')}</th>
                  <th>{t('common.risk')}</th>
                  <th>
                    <span className="th-inner">{t('common.signals')}<InfoTip align="end">{t('risk.caveatLong')}</InfoTip></span>
                  </th>
                </tr>
              </thead>
              <tbody ref={bodyRef}>
                {items.map(u => (
                  <tr key={u.code} data-key={u.code} className="clickable" onClick={() => navigate(`/units/${encodeId(u.code)}`)}>
                    <td className="cell-strong">
                      <Link to={`/units/${encodeId(u.code)}`} className="cell-truncate" style={{ maxWidth: 340 }} title={u.name} onClick={e => e.stopPropagation()}>
                        {u.name || u.code}
                      </Link>
                    </td>
                    <td className="cell-mono"><span className="cell-truncate" style={{ maxWidth: 140 }} title={u.code}>{u.code}</span></td>
                    <td className="num tabular">{u.total_tenders?.toLocaleString(locale)}</td>
                    <td><ScoreBar score={u.risk_score} /></td>
                    <td><SignalCount value={u.confidence || 0} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="card-foot">
          <span className="label">{t('common.results', { count: data?.total ?? 0, value: (data?.total ?? 0).toLocaleString(locale) })}</span>
          <Pagination page={data?.page || 1} totalPages={data?.total_pages || 1} onPageChange={setPage} />
        </div>
      </section>
    </Reveal>
  )
}
