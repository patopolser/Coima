import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fetchUnit } from '../api/client'
import { LoadingScreen, QueryState } from '../components/ui'
import EntityDetail from '../components/entity/EntityDetail'
import { decodeId } from '../utils/ids'
import { useLang } from '../hooks/useLang'

export default function UnitDetail() {
  // Code arrives base64url-encoded (UOC codes can contain "/"); decode to the real code.
  const code = decodeId(useParams().code)
  const { t, lang, locale } = useLang()
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['unit', lang, code],
    queryFn: () => fetchUnit(code),
  })

  if (isLoading) return <LoadingScreen />
  if (!data) return <QueryState error={error} onRetry={refetch} notFoundTitle={t('unitDetail.notFound')} />

  return (
    <EntityDetail
      title={data.name || code}
      meta={
        <>
          <span className="mono">{code}</span>
          {data.total_tenders != null && (
            <span>{t('unitDetail.tendersCount', { count: data.total_tenders, value: data.total_tenders.toLocaleString(locale) })}</span>
          )}
        </>
      }
      back={{ to: '/units', label: t('nav.units') }}
      risk={data.risk}
      findings={data.findings}
      searchTerm={code}
      graphLink={`/graph?type=unit&id=${encodeURIComponent(code)}`}
    />
  )
}
