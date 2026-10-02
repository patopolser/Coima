import { useRef, useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { fetchRiskScores, fetchAllFlags } from '../api/client'
import { SearchBar, Pagination, ScoreBar, SignalCount, LoadingScreen, ErrorState, EmptyState, SortTh, InfoTip } from '../components/ui'
import { Reveal, useAnimatedList } from '../motion'
import { useCheckLabels } from '../hooks/useCheckLabels'
import { useLang } from '../hooks/useLang'

export default function Providers() {
  const navigate = useNavigate()
  const { t, lang, locale } = useLang()
  const [params] = useSearchParams()
  const labels = useCheckLabels()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState(params.get('search') || '')
  const [minScore, setMinScore] = useState(0)
  const [flag, setFlag] = useState('')
  const [sort, setSort] = useState('score')
  const [dir, setDir] = useState('desc')
  const bodyRef = useRef(null)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['providers', lang, page, search, minScore, flag, sort, dir],
    queryFn: () => fetchRiskScores({ page, per_page: 50, search, min_score: minScore, flag, sort, dir }),
    placeholderData: keepPreviousData,
  })
  const flagsQ = useQuery({ queryKey: ['flags', lang], queryFn: fetchAllFlags })
  const items = data?.items || []
  useAnimatedList(bodyRef, items.map(s => s.cuit).join('|'))

  const toggleSort = col => {
    if (sort === col) setDir(d => (d === 'asc' ? 'desc' : 'asc'))
    else { setSort(col); setDir(col === 'score' ? 'desc' : 'asc') }
    setPage(1)
  }

  if (isLoading) return <LoadingScreen />
  if (error && !data) return <ErrorState error={error} onRetry={refetch} />

  return (
    <Reveal>
      <div className="page-head">
        <h1 className="page-title">{t('providers.title')}</h1>
        <span className="chip tabular">{(data?.total ?? 0).toLocaleString(locale)}</span>
      </div>

      <div className="list-toolbar" data-reveal="1">
        <SearchBar
          value={search}
          onChange={v => { setSearch(v); setPage(1) }}
          placeholder={t('providers.searchPlaceholder')}
          autoFocus={params.get('focus') === 'search'}
        />
        <select className="input select" style={{ width: 170 }} value={minScore} aria-label={t('providers.minScore')}
          onChange={e => { setMinScore(+e.target.value); setPage(1) }}>
          <option value={0}>{t('providers.allScores')}</option>
          <option value={40}>{t('providers.fromLevel', { level: t('risk.medium') })}</option>
          <option value={60}>{t('providers.fromLevel', { level: t('risk.high') })}</option>
          <option value={80}>{t('risk.critical')}</option>
        </select>
        <select className="input select" style={{ width: 230 }} value={flag} aria-label={t('providers.detector')}
          onChange={e => { setFlag(e.target.value); setPage(1) }}>
          <option value="">{t('providers.allDetectors')}</option>
          {(flagsQ.data || []).map(f => <option key={f} value={f}>{labels[f] || f.replace(/_/g, ' ')}</option>)}
        </select>
      </div>

      <section className="card" data-reveal="2" style={{ overflow: 'hidden' }}>
        {items.length === 0 ? (
          <EmptyState title={t('common.noResults')} />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <SortTh col="company" sort={sort} dir={dir} onSort={toggleSort}>{t('providers.company')}</SortTh>
                  <SortTh col="cuit" sort={sort} dir={dir} onSort={toggleSort}>{t('providers.cuit')}</SortTh>
                  <SortTh col="score" sort={sort} dir={dir} onSort={toggleSort}>
                    {t('common.risk')}
                  </SortTh>
                  <th>
                    <span className="th-inner">{t('common.signals')}<InfoTip align="end">{t('risk.caveatLong')}</InfoTip></span>
                  </th>
                </tr>
              </thead>
              <tbody ref={bodyRef}>
                {items.map(s => (
                  <tr key={s.cuit} data-key={s.cuit} className="clickable" onClick={() => navigate(`/companies/${s.cuit}`)}>
                    <td className="cell-strong">
                      <Link to={`/companies/${s.cuit}`} className="cell-truncate" style={{ maxWidth: 320 }} onClick={e => e.stopPropagation()}>
                        {s.company || '—'}
                      </Link>
                    </td>
                    <td className="cell-mono">{s.cuit}</td>
                    <td><ScoreBar score={s.score} /></td>
                    <td><SignalCount value={s.confidence || 0} /></td>
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
