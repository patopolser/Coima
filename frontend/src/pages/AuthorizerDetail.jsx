import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fetchAuthorizer, fetchChecks } from '../api/client'
import { LoadingScreen, EmptyState, RiskBadge, ConfidenceMeter, FlagPill } from '../components/ui'
import EvidenceBreakdown from '../components/EvidenceBreakdown'
import LegalNote from '../components/LegalNote'
import { normalizeColumns, renderColumnCell } from '../utils/checkColumns'
import { decodeId } from '../utils/ids'
import { useLang } from '../hooks/useLang'

export default function AuthorizerDetail() {
  const name = decodeId(useParams().name)
  const { t, lang } = useLang()
  const { data, isLoading } = useQuery({
    queryKey: ['authorizer', lang, name],
    queryFn: () => fetchAuthorizer(name),
  })
  const checksQ = useQuery({ queryKey: ['checks', lang], queryFn: fetchChecks })

  if (isLoading) return <LoadingScreen />
  if (!data) return <EmptyState title={t('authorizerDetail.notFound')} />

  const checkMeta = {}
  ;(checksQ.data || []).forEach(c => { checkMeta[c.key] = c })
  const risk = data.risk
  const findings = data.findings || {}

  return (
    <>
      <div className="page-header">
        <div className="breadcrumb">
          <Link to="/authorizers">{t('authorizerDetail.breadcrumb')}</Link>
          <span className="breadcrumb-sep">›</span>
          <span>{name}</span>
        </div>
        <h1 className="page-title">{data.authorizer || name}</h1>
        <p className="page-subtitle">{t('authorizerDetail.subtitle')}</p>
        <LegalNote />
      </div>

      {risk && (
        <div className="card card-body flex items-center gap-8 mb-8" style={{ flexWrap: 'wrap' }}>
          <RiskBadge score={risk.score} />
          <div style={{ flex: 1 }}>
            <div className="flex items-center gap-3 mb-3" style={{ flexWrap: 'wrap' }}>
              <span className="font-display font-semibold" style={{ fontSize: '1.125rem' }}>{t('companyDetail.riskProfile')}</span>
              {risk.evidence_breakdown?.multiplier > 1 && risk.base_score != null && (
                <span className="badge" style={{ background: 'var(--bg-elevated)', color: 'var(--text-muted)' }}>
                  {t('companyDetail.baseScore', { score: risk.base_score })} · ⚡ {t('companyDetail.synergyApplied', { multiplier: risk.evidence_breakdown.multiplier })}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 mb-3">
              <span className="text-xs text-muted">{t('companyDetail.confidence')}:</span>
              <ConfidenceMeter value={risk.confidence || 0} title={t('companyDetail.confidenceVectors', { count: risk.confidence || 0 })} />
            </div>
            <div className="flex gap-2 flex-wrap">
              {(Array.isArray(risk.flags) ? risk.flags : (risk.flags || '').split(','))
                .map(f => (typeof f === 'string' ? f.trim() : f)).filter(Boolean)
                .map(f => <FlagPill key={f} flag={f} />)}
            </div>
          </div>
        </div>
      )}

      {risk?.evidence_breakdown && (
        <EvidenceBreakdown breakdown={risk.evidence_breakdown} checkMeta={checkMeta} />
      )}

      {Object.keys(findings).length === 0 && !risk && (
        <EmptyState title={t('authorizerDetail.clearTitle')} />
      )}

      {Object.entries(findings).map(([key, rows]) => {
        if (!rows?.length) return null
        const meta = checkMeta[key] || {}
        const cols = normalizeColumns(meta.columns || [], meta)
        return (
          <div key={key} className="card mb-6" style={{ overflow: 'hidden' }}>
            <div className="card-header">
              <span className="font-display font-semibold">{meta.label || key}</span>
              <span className="badge badge-accent">{rows.length} {rows.length !== 1 ? t('common.findingsPlural') : t('common.finding')}</span>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead><tr>{cols.map(col => <th key={col.key}>{col.label}</th>)}</tr></thead>
                <tbody>
                  {rows.slice(0, 50).map((row, ri) => (
                    <tr key={ri}>
                      {cols.map(col => <td key={col.key}>{renderColumnCell(col, row, meta)}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      })}
    </>
  )
}
