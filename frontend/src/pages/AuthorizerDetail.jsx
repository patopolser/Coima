import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fetchAuthorizer } from '../api/client'
import { LoadingScreen, QueryState } from '../components/ui'
import EntityDetail from '../components/entity/EntityDetail'
import { decodeId } from '../utils/ids'
import { useLang } from '../hooks/useLang'

export default function AuthorizerDetail() {
  const name = decodeId(useParams().name)
  const { t, lang } = useLang()
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['authorizer', lang, name],
    queryFn: () => fetchAuthorizer(name),
  })

  if (isLoading) return <LoadingScreen />
  if (!data) return <QueryState error={error} onRetry={refetch} notFoundTitle={t('authorizerDetail.notFound')} />

  return (
    <EntityDetail
      title={data.authorizer || name}
      meta={<span>{t('authorizerDetail.role')}</span>}
      back={{ to: '/authorizers', label: t('nav.authorizers') }}
      risk={data.risk}
      findings={data.findings}
      searchTerm={data.authorizer || name}
      graphLink={`/graph?type=authorizer&id=${encodeURIComponent(data.authorizer || name)}`}
    />
  )
}
