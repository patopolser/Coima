import { useParams, Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fetchCompany, fetchChecks } from '../api/client'
import { RiskBadge, FlagPill, LoadingScreen, EmptyState, ConfidenceMeter } from '../components/ui'
import EvidenceBreakdown from '../components/EvidenceBreakdown'
import LegalNote from '../components/LegalNote'
import { normalizeColumns, renderColumnCell } from '../utils/checkColumns'
import { useLang } from '../hooks/useLang'

export default function CompanyDetail() {
  const { t, lang } = useLang()
  const { cuit } = useParams()
  const navigate = useNavigate()
  const { data, isLoading } = useQuery({ queryKey: ['company', lang, cuit], queryFn: () => fetchCompany(cuit) })
  const checksQ = useQuery({ queryKey: ['checks', lang], queryFn: fetchChecks })

  if (isLoading) return <LoadingScreen />
  if (!data) return <EmptyState title={t('companyDetail.notFound')} />

  const checkMeta = {}
  ;(checksQ.data || []).forEach(c => { checkMeta[c.key] = c })
  const rs = data.risk_score
  const findings = data.findings || {}

  return (
    <>
      <div className="page-header">
        <div className="breadcrumb">
          <Link to="/providers">{t('companyDetail.breadcrumb')}</Link>
          <span className="breadcrumb-sep">›</span>
          <span>{cuit}</span>
        </div>
        <div className="flex items-center justify-between flex-wrap gap-4">
          <div>
            <h1 className="page-title">{rs?.company && rs.company !== '—' ? rs.company : t('companyDetail.companyFallback', { cuit })}</h1>
            <p className="page-subtitle text-mono">{t('companyDetail.cuit', { cuit })}</p>
            <LegalNote />
          </div>
        </div>
      </div>

      {rs && (
        <div className="card card-body flex items-center gap-8 mb-8" style={{ flexWrap: 'wrap' }}>
          <RiskBadge score={rs.score} />
          <div style={{ flex: 1 }}>
            <div className="flex items-center gap-3 mb-3" style={{ flexWrap: 'wrap' }}>
              <span className="font-display font-semibold" style={{ fontSize: '1.125rem' }}>{t('companyDetail.riskProfile')}</span>
              {rs.evidence_breakdown?.multiplier > 1 && rs.base_score != null && (
                <span className="badge" style={{ background: 'var(--bg-elevated)', color: 'var(--text-muted)' }}>
                  {t('companyDetail.baseScore', { score: rs.base_score })} · ⚡ {t('companyDetail.synergyApplied', { multiplier: rs.evidence_breakdown.multiplier })}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 mb-3">
              <span className="text-xs text-muted">{t('companyDetail.confidence')}:</span>
              <ConfidenceMeter
                value={rs.confidence || 0}
                title={t('companyDetail.confidenceVectors', { count: rs.confidence || 0 })}
              />
            </div>
            <div className="flex gap-2 flex-wrap">
              {(Array.isArray(rs.flags) ? rs.flags : (rs.flags || '').split(','))
                .map(f => (typeof f === 'string' ? f.trim() : f))
                .filter(Boolean)
                .map(f => (
                  <FlagPill key={f} flag={f} onClick={() => navigate(`/checks/${f}`)} />
                ))}
            </div>
          </div>
        </div>
      )}

      {rs?.evidence_breakdown && (
        <EvidenceBreakdown breakdown={rs.evidence_breakdown} checkMeta={checkMeta} />
      )}

      {Object.keys(findings).length === 0 && (
        <EmptyState title={t('companyDetail.clearTitle')} text={t('companyDetail.clearText')} />
      )}

      {Object.entries(findings).map(([checkName, rows]) => {
        if (!rows?.length) return null
        const meta = checkMeta[checkName] || {}
        const cols = normalizeColumns(meta.columns || [], meta)
        return (
          <div key={checkName} className="card mb-6" style={{ overflow: 'hidden' }}>
            <div className="card-header">
              <div className="flex items-center gap-3">
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--accent)' }} />
                <span className="font-display font-semibold">{meta.label || checkName}</span>
              </div>
              <span className="badge badge-accent">{rows.length} {rows.length !== 1 ? t('common.findingsPlural') : t('common.finding')}</span>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead><tr>{cols.map(col => <th key={col.key}>{col.label}</th>)}</tr></thead>
                <tbody>
                  {rows.slice(0, 50).map((row, ri) => (
                    <tr key={ri}>
                      {cols.map(col => (
                        <td key={col.key}>
                          {renderColumnCell(col, row, meta, { cuit })}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {rows.length > 50 && (
              <div style={{ padding: '12px 16px', borderTop: '1px solid var(--border)' }} className="flex items-center justify-between">
                <span className="text-xs text-muted">{t('common.showingFirst')}</span>
                <Link to={`/checks/${checkName}?search=${cuit}`} className="text-xs text-accent" style={{ fontWeight: 600 }}>{t('common.viewAll', { count: rows.length })}</Link>
              </div>
            )}
          </div>
        )
      })}
    </>
  )
}
