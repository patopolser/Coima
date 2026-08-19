import { useLang } from '../hooks/useLang'

/*
 * Renders the smart-scoring evidence_breakdown produced by the backend (Fase 2):
 *   - matched syndromes (correlated patterns that multiplied the score)
 *   - per-check contribution (weight x intensity)
 *   - co-bidding network features (recorded, score-neutral)
 *
 * checkMeta: { [key]: { label, color } } — used to label/colour each vector.
 */
export default function EvidenceBreakdown({ breakdown, checkMeta = {} }) {
  const { t } = useLang()
  if (!breakdown) return null

  const checks = breakdown.checks || []
  const synergies = breakdown.synergies || []
  const features = breakdown.features || null
  const labelOf = key => checkMeta[key]?.label || key.replace(/_/g, ' ')

  return (
    <div className="card mb-6" style={{ overflow: 'hidden' }}>
      <div className="card-header">
        <div>
          <div className="font-display font-semibold">{t('companyDetail.evidenceTitle')}</div>
          <div className="text-xs text-muted" style={{ marginTop: 2 }}>{t('companyDetail.evidenceSubtitle')}</div>
        </div>
      </div>

      <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        {/* Synergies */}
        <div>
          <div className="text-sm font-semibold" style={{ marginBottom: 6 }}>{t('companyDetail.synergyTitle')}</div>
          {synergies.length === 0 ? (
            <div className="text-xs text-muted">{t('companyDetail.noSynergy')}</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div className="text-xs text-muted">{t('companyDetail.synergyNote')}</div>
              {synergies.map((s, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between"
                  style={{
                    padding: '8px 12px', borderRadius: 8,
                    background: 'var(--bg-elevated)', border: '1px solid var(--border)',
                  }}
                >
                  <div className="flex items-center gap-2" style={{ flexWrap: 'wrap' }}>
                    <span style={{ color: 'var(--risk-high)' }}>⚡</span>
                    <span className="text-sm">{s.label}</span>
                    <span className="flex gap-1" style={{ flexWrap: 'wrap' }}>
                      {(s.keys || []).map(k => (
                        <span key={k} className="flag-pill" style={{ fontSize: 10 }}>{labelOf(k)}</span>
                      ))}
                    </span>
                  </div>
                  <span className="text-mono font-semibold" style={{ color: 'var(--risk-high)', whiteSpace: 'nowrap' }}>
                    ×{s.multiplier}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Per-check contribution */}
        {checks.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t('companyDetail.vector')}</th>
                  <th style={{ textAlign: 'right' }}>{t('companyDetail.findingsCount')}</th>
                  <th style={{ textAlign: 'right' }}>{t('companyDetail.weight')}</th>
                  <th style={{ textAlign: 'right' }}>{t('companyDetail.intensity')}</th>
                  <th style={{ textAlign: 'right' }}>{t('companyDetail.contribution')}</th>
                </tr>
              </thead>
              <tbody>
                {checks.map(c => {
                  const color = checkMeta[c.check]?.color
                  return (
                    <tr key={c.check}>
                      <td>
                        <span className="flex items-center gap-2">
                          {color && <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, display: 'inline-block' }} />}
                          {labelOf(c.check)}
                        </span>
                      </td>
                      <td className="text-mono" style={{ textAlign: 'right' }}>{c.count}</td>
                      <td className="text-mono text-muted" style={{ textAlign: 'right' }}>{c.weight}</td>
                      <td className="text-mono text-muted" style={{ textAlign: 'right' }}>{c.intensity}</td>
                      <td className="text-mono font-semibold" style={{ textAlign: 'right' }}>{c.contribution}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Network features (score-neutral) */}
        {features && (features.cobid_degree != null || features.cobid_betweenness != null) && (
          <div>
            <div className="text-sm font-semibold" style={{ marginBottom: 2 }}>{t('companyDetail.networkTitle')}</div>
            <div className="text-xs text-muted" style={{ marginBottom: 8 }}>{t('companyDetail.networkNote')}</div>
            <div className="flex gap-6" style={{ flexWrap: 'wrap' }}>
              {features.cobid_degree != null && (
                <div>
                  <div className="text-xs text-muted">{t('companyDetail.degree')}</div>
                  <div className="font-display font-semibold" style={{ fontSize: '1.25rem' }}>{features.cobid_degree}</div>
                </div>
              )}
              {features.cobid_betweenness != null && (
                <div>
                  <div className="text-xs text-muted">{t('companyDetail.betweenness')}</div>
                  <div className="font-display font-semibold" style={{ fontSize: '1.25rem' }}>{features.cobid_betweenness}</div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
