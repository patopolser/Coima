import { useRef, useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { fetchAuthorizers } from '../api/client'
import { SearchBar, Pagination, ScoreBar, SignalCount, LoadingScreen, ErrorState, EmptyState, InfoTip } from '../components/ui'
import { Reveal, useAnimatedList } from '../motion'
import { encodeId } from '../utils/ids'
import { useLang } from '../hooks/useLang'

export default function Authorizers() {
  const { t, lang, locale } = useLang()
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const bodyRef = useRef(null)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['authorizers', lang, page, search],
    queryFn: () => fetchAuthorizers({ page, per_page: 50, search }),
    placeholderData: keepPreviousData,
  })
  const items = data?.items || []
  useAnimatedList(bodyRef, items.map(a => a.authorizer).join('|'))

  if (isLoading) return <LoadingScreen />
  if (error && !data) return <ErrorState error={error} onRetry={refetch} />

  return (
    <Reveal>
      <div className="page-head">
        <h1 className="page-title">{t('authorizers.title')}</h1>
        <span className="chip tabular">{(data?.total ?? 0).toLocaleString(locale)}</span>
      </div>

      <div className="list-toolbar" data-reveal="1">
        <SearchBar value={search} onChange={v => { setSearch(v); setPage(1) }} placeholder={t('authorizers.searchPlaceholder')} />
      </div>

      <section className="card" data-reveal="2" style={{ overflow: 'hidden' }}>
        {items.length === 0 ? (
          <EmptyState title={t('common.noResults')} />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t('authorizers.name')}</th>
                  <th>{t('common.risk')}</th>
                  <th>
                    <span className="th-inner">{t('common.signals')}<InfoTip align="end">{t('risk.caveatLong')}</InfoTip></span>
                  </th>
                </tr>
              </thead>
              <tbody ref={bodyRef}>
                {items.map(a => (
                  <tr key={a.authorizer} data-key={a.authorizer} className="clickable" onClick={() => navigate(`/authorizers/${encodeId(a.authorizer)}`)}>
                    <td className="cell-strong">
                      <Link to={`/authorizers/${encodeId(a.authorizer)}`} className="cell-truncate" style={{ maxWidth: 420 }} onClick={e => e.stopPropagation()}>
                        {a.authorizer}
                      </Link>
                    </td>
                    <td><ScoreBar score={a.risk_score} /></td>
                    <td><SignalCount value={a.confidence || 0} /></td>
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
