import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { fetchInvestigations } from '../api/client'
import { LoadingScreen, EmptyState } from '../components/ui'
import { useLang } from '../hooks/useLang'

const STATUS_BADGE = {
  open: 'badge-accent',
  in_progress: 'badge-amber',
  closed: 'badge-green',
  archived: 'badge-red',
}

export default function Investigations() {
  const navigate = useNavigate()
  const { t, lang } = useLang()
  const { data, isLoading } = useQuery({
    queryKey: ['investigations', lang],
    queryFn: () => fetchInvestigations(),
  })

  if (isLoading) return <LoadingScreen />
  const invs = data || []

  return (
    <>
      <div className="page-header flex items-center justify-between">
        <div>
          <h1 className="page-title">{t('investigations.title')}</h1>
          <p className="page-subtitle">{t('investigations.subtitle')}</p>
        </div>
        <button className="btn btn-primary" onClick={() => navigate('/investigations/new')}>
          {t('investigations.new')}
        </button>
      </div>

      {invs.length === 0 ? (
        <EmptyState title={t('investigations.emptyTitle')} text={t('investigations.emptyText')} />
      ) : (
        <div className="grid grid-2" style={{ gap: 16 }}>
          {invs.map(inv => (
            <div key={inv.id} className="card card-body card-glow" onClick={() => navigate(`/investigations/${inv.id}`)} style={{ cursor: 'pointer' }}>
              <div className="flex items-center justify-between mb-3">
                <span className="font-display font-semibold">{inv.title}</span>
                <span className={`badge ${STATUS_BADGE[inv.status] || 'badge-accent'}`}>
                  {t(`investigations.status.${inv.status}`, { defaultValue: inv.status?.replace('_', ' ') })}
                </span>
              </div>
              <div className="flex gap-2 flex-wrap mb-3">
                {(inv.subjects || []).map((s, i) => (
                  <span key={i} className="flag-pill">{s.name || s.id}</span>
                ))}
              </div>
              <div className="text-xs text-muted">{t('common.created', { date: inv.created_at?.slice(0, 10) })}</div>
            </div>
          ))}
        </div>
      )}
    </>
  )
}
