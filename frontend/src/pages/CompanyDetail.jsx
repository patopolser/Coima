import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fetchCompany } from '../api/client'
import { LoadingScreen, QueryState } from '../components/ui'
import EntityDetail from '../components/entity/EntityDetail'
import { useLang } from '../hooks/useLang'

export default function CompanyDetail() {
  const { t, lang } = useLang()
  const { cuit } = useParams()
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['company', lang, cuit],
    queryFn: () => fetchCompany(cuit),
  })

  if (isLoading) return <LoadingScreen />
  if (!data) return <QueryState error={error} onRetry={refetch} notFoundTitle={t('companyDetail.notFound')} />

  const rs = data.risk_score
  const name = rs?.company && rs.company !== '—' ? rs.company : t('companyDetail.companyFallback', { cuit })

  return (
    <EntityDetail
      title={name}
      meta={<span className="mono">{t('companyDetail.cuit', { cuit })}</span>}
      back={{ to: '/providers', label: t('nav.providers') }}
      risk={rs}
      findings={data.findings}
      searchTerm={cuit}
      graphLink={`/graph?type=provider&id=${encodeURIComponent(cuit)}`}
      cellOptions={{ cuit }}
    />
  )
}
