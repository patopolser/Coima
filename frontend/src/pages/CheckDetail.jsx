import { useRef, useState } from 'react'
import { useParams, useSearchParams, Link } from 'react-router-dom'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { fetchCheck } from '../api/client'
import { normalizeColumns, renderColumnCell } from '../utils/checkColumns'
import { SearchBar, Pagination, LoadingScreen, QueryState, EmptyState, SortTh, InfoTip } from '../components/ui'
import { Reveal, useAnimatedList } from '../motion'
import { IconArrowLeft } from '../components/icons'
import { useLang } from '../hooks/useLang'

// First sentence of the backend description; the rest stays one click away.
function firstSentence(text = '') {
  const m = text.match(/^.+?[.!?](\s|$)/)
  return m ? m[0].trim() : text
}

export default function CheckDetail() {
  const { t, lang, locale } = useLang()
  const { key } = useParams()
  const [params] = useSearchParams()
  const [page, setPage] = useState(1)
  // Entity pages link here with ?search=<cuit|code|name> to pre-filter.
  const [search, setSearch] = useState(params.get('search') || '')
  const [sort, setSort] = useState(null)
  const [dir, setDir] = useState('asc')
  const [fullDesc, setFullDesc] = useState(false)
  const bodyRef = useRef(null)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['check', lang, key, page, search, sort, dir],
    queryFn: () => fetchCheck(key, { page, per_page: 50, search, sort, dir }),
    placeholderData: keepPreviousData,
  })
  const items = data?.items || []
  useAnimatedList(bodyRef, `${page}|${sort}|${dir}|${search}|${items.length}`)

  const toggleSort = col => {
    if (sort === col) setDir(d => (d === 'asc' ? 'desc' : 'asc'))
    else { setSort(col); setDir('asc') }
    setPage(1)
  }

  if (isLoading) return <LoadingScreen />
  if (!data) return <QueryState error={error} onRetry={refetch} notFoundTitle={t('checkDetail.notFound')} />

  const meta = {
    url_columns: data.url_columns || {},
    cuit_columns: data.cuit_columns || [],
    unit_columns: data.unit_columns || [],
  }
  const columns = normalizeColumns(data.columns || [], meta)
  const desc = data.description || ''
  const short = firstSentence(desc)

  return (
    <Reveal>
      <Link to="/" className="back-link"><IconArrowLeft size={14} /> {t('nav.dashboard')}</Link>
      <div className="page-head">
        <h1 className="page-title">{data.label}</h1>
        <span className="chip tabular">{t('checkDetail.findings', { count: data.total_findings ?? 0, value: (data.total_findings ?? 0).toLocaleString(locale) })}</span>
        <span className="chip tabular">{t('checkDetail.weight', { value: data.weight })}</span>
      </div>
      {desc && (
        <p className="check-desc" data-reveal="1">
          {fullDesc ? desc : short}
          {short !== desc && (
            <button type="button" onClick={() => setFullDesc(v => !v)}>
              {fullDesc ? t('common.showLess') : t('common.readMore')}
            </button>
          )}
        </p>
      )}

      <div className="list-toolbar" data-reveal="2">
        <SearchBar value={search} onChange={v => { setSearch(v); setPage(1) }} placeholder={t('checkDetail.searchPlaceholder')} />
        <InfoTip>{t('risk.caveatLong')}</InfoTip>
      </div>

      <section className="card" data-reveal="3" style={{ overflow: 'hidden' }}>
        {items.length === 0 ? (
          <EmptyState title={t('common.noResults')} />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  {columns.map(col => (
                    <SortTh key={col.key} col={col.key} sort={sort} dir={dir} onSort={toggleSort}>{col.label}</SortTh>
                  ))}
                </tr>
              </thead>
              <tbody ref={bodyRef}>
                {items.map((row, ri) => (
                  <tr key={ri} data-key={`${page}-${ri}`}>
                    {columns.map(col => <td key={col.key}>{renderColumnCell(col, row, meta)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="card-foot">
          <span className="label">{t('common.results', { count: data.total ?? 0, value: (data.total ?? 0).toLocaleString(locale) })}</span>
          <Pagination page={data.page} totalPages={data.total_pages} onPageChange={setPage} />
        </div>
      </section>
    </Reveal>
  )
}
