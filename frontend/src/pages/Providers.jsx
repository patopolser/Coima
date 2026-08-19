import { useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { fetchRiskScores, fetchAllFlags } from '../api/client'
import { SearchBar, Pagination, ScoreBar, FlagPillList, LoadingScreen, ConfidenceMeter } from '../components/ui'
import LegalNote from '../components/LegalNote'
import { useLang } from '../hooks/useLang'

export default function Providers() {
  const navigate = useNavigate()
  const { t, lang, locale } = useLang()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [minScore, setMinScore] = useState(0)
  const [flag, setFlag] = useState('')
  const [sort, setSort] = useState('score')
  const [dir, setDir] = useState('desc')

  const { data, isLoading } = useQuery({
    queryKey: ['providers', lang, page, search, minScore, flag, sort, dir],
    queryFn: () => fetchRiskScores({ page, per_page: 50, search, min_score: minScore, flag, sort, dir }),
    placeholderData: keepPreviousData,
  })
  const flagsQ = useQuery({ queryKey: ['flags', lang], queryFn: fetchAllFlags })

  const toggleSort = col => {
    if (sort === col) setDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSort(col); setDir('desc') }
    setPage(1)
  }

  const sortIcon = col => sort === col ? (dir === 'desc' ? ' ↓' : ' ↑') : ''

  if (isLoading) return <LoadingScreen />

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">{t('providers.title')}</h1>
        <p className="page-subtitle">{t('providers.subtitle')}</p>
        <LegalNote />
      </div>

      <div className="flex gap-3 mb-6 flex-wrap">
        <SearchBar value={search} onChange={v => { setSearch(v); setPage(1) }} placeholder={t('providers.searchPlaceholder')} style={{ flex: '1 1 240px' }} />
        <select className="input select" style={{ width: 140 }} value={minScore} onChange={e => { setMinScore(+e.target.value); setPage(1) }}>
          <option value={0}>{t('providers.allScores')}</option>
          <option value={20}>≥ 20</option>
          <option value={40}>≥ 40</option>
          <option value={60}>≥ 60</option>
          <option value={80}>≥ 80</option>
        </select>
        <select className="input select" style={{ width: 180 }} value={flag} onChange={e => { setFlag(e.target.value); setPage(1) }}>
          <option value="">{t('providers.allFlags')}</option>
          {(flagsQ.data || []).map(f => <option key={f} value={f}>{f.replace(/_/g, ' ')}</option>)}
        </select>
      </div>

      <div className="card" style={{ overflow: 'hidden' }}>
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th className={sort === 'company' ? 'sorted' : ''} onClick={() => toggleSort('company')}>{t('providers.company')}{sortIcon('company')}</th>
                <th className={sort === 'cuit' ? 'sorted' : ''} onClick={() => toggleSort('cuit')}>{t('providers.cuit')}{sortIcon('cuit')}</th>
                <th className={sort === 'score' ? 'sorted' : ''} onClick={() => toggleSort('score')} style={{ minWidth: 150 }}>{t('providers.score')}{sortIcon('score')}</th>
                <th>{t('providers.confidence')}</th>
                <th>{t('providers.flags')}</th>
              </tr>
            </thead>
            <tbody>
              {(data?.items || []).map(s => {
                const counts = {}
                ;(s.evidence_breakdown?.checks || []).forEach(c => { counts[c.check] = c.count })
                return (
                <tr key={s.cuit} className="clickable" onClick={() => navigate(`/companies/${s.cuit}`)}>
                  <td className="cell-bold truncate" style={{ maxWidth: 260 }}>{s.company || '—'}</td>
                  <td className="cell-mono">{s.cuit}</td>
                  <td>
                    <div className="flex items-center gap-2">
                      <ScoreBar score={s.score} />
                      {s.evidence_breakdown?.multiplier > 1 && (
                        <span title={`×${s.evidence_breakdown.multiplier}`} style={{ color: 'var(--risk-high)' }}>⚡</span>
                      )}
                    </div>
                  </td>
                  <td><ConfidenceMeter value={s.confidence || 0} /></td>
                  <td>
                    <FlagPillList items={
                      (Array.isArray(s.flags) ? s.flags : (s.flags || '').split(','))
                        .map(f => typeof f === 'string' ? f.trim() : f)
                        .filter(Boolean)
                        .map(f => ({ flag: f, count: counts[f] }))
                    } />
                  </td>
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
