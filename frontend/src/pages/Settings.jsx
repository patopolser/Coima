import { useEffect, useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchConfig, updateConfig } from '../api/client'

const COLOR_DOT = {
  red: '#ef4444', orange: '#f97316', yellow: '#eab308', amber: '#f59e0b',
  purple: '#a855f7', fuchsia: '#d946ef', pink: '#ec4899', rose: '#f43f5e',
  cyan: '#06b6d4', teal: '#14b8a6', emerald: '#10b981', green: '#22c55e',
  indigo: '#6366f1', violet: '#8b5cf6', lime: '#84cc16', slate: '#94a3b8',
}

function CheckCard({ check, thresholds, onToggle, onWeightChange, onThresholdChange }) {
  const { t } = useTranslation()
  const dot = COLOR_DOT[check.color] || COLOR_DOT.slate
  const hasThresholds = check.check_thresholds && Object.keys(check.check_thresholds).length > 0

  return (
    <div
      className="card"
      style={{
        marginBottom: 12,
        padding: '18px 20px',
        opacity: check.enabled ? 1 : 0.55,
        transition: 'opacity 0.15s',
      }}
    >
      {/* Card header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: hasThresholds ? 18 : 0 }}>
        <span
          style={{
            width: 10,
            height: 10,
            borderRadius: '50%',
            background: dot,
            flexShrink: 0,
            marginTop: 5,
            display: 'inline-block',
          }}
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontWeight: 600,
              fontSize: 15,
              color: 'var(--text-primary)',
              marginBottom: 3,
              overflowWrap: 'anywhere',
            }}
          >
            {check.label}
          </div>
          {check.description && (
            <div
              style={{
                fontSize: 12.5,
                color: 'var(--text-muted)',
                lineHeight: 1.5,
                overflowWrap: 'anywhere',
              }}
            >
              {check.description}
            </div>
          )}
        </div>

        {/* Controls: toggle + weight */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexShrink: 0 }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
              {t('settings.weight')}
            </div>
            <input
              type="number"
              min={0}
              max={100}
              value={check.weight}
              onChange={e => onWeightChange(check.key, Number(e.target.value))}
              style={{
                width: 64,
                textAlign: 'center',
                padding: '4px 6px',
                borderRadius: 6,
                border: '1px solid var(--border)',
                background: 'var(--bg-elevated)',
                color: 'var(--text-primary)',
                fontSize: 14,
              }}
            />
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
              {t('settings.defaultWeight', { value: check.default_weight })}
            </div>
          </div>

          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
              {t('settings.enabled')}
            </div>
            <button
              onClick={() => onToggle(check.key, !check.enabled)}
              style={{
                padding: '5px 16px',
                borderRadius: 20,
                border: 'none',
                cursor: 'pointer',
                fontWeight: 600,
                fontSize: 12,
                background: check.enabled ? 'var(--accent)' : 'var(--bg-active)',
                color: check.enabled ? '#fff' : 'var(--text-muted)',
                transition: 'background 0.15s',
                display: 'block',
              }}
            >
              {check.enabled ? 'ON' : 'OFF'}
            </button>
          </div>
        </div>
      </div>

      {/* Per-check thresholds */}
      {hasThresholds && (
        <div
          style={{
            borderTop: '1px solid var(--border)',
            paddingTop: 14,
            display: 'flex',
            flexWrap: 'wrap',
            gap: '12px 20px',
          }}
        >
          {Object.entries(check.check_thresholds).map(([key, defaultVal]) => (
            <div key={key} style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              <label
                style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'monospace' }}
              >
                {key}
              </label>
              <input
                type="number"
                step="any"
                value={thresholds[key] ?? defaultVal}
                onChange={e => {
                  const raw = e.target.value
                  const num = raw.includes('.') ? parseFloat(raw) : parseInt(raw, 10)
                  onThresholdChange(key, isNaN(num) ? raw : num)
                }}
                style={{
                  width: 110,
                  padding: '4px 8px',
                  borderRadius: 6,
                  border: '1px solid var(--border)',
                  background: 'var(--bg-elevated)',
                  color: 'var(--text-primary)',
                  fontSize: 13,
                }}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function Settings() {
  const { t, i18n } = useTranslation()
  const [checks, setChecks] = useState([])
  const [thresholds, setThresholds] = useState({})
  const [status, setStatus] = useState('idle')
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const data = await fetchConfig()
      setChecks(data.available_checks || [])
      setThresholds(data.thresholds || {})
    } catch (err) {
      console.error('Failed to load config', err)
    } finally {
      setLoading(false)
    }
  }, [])

  // Re-fetch when the UI language changes so check labels/descriptions
  // (which are localized server-side via Accept-Language) follow the locale.
  useEffect(() => { load() }, [load, i18n.language])

  const handleToggle = (key, enabled) => {
    setChecks(prev => prev.map(c => c.key === key ? { ...c, enabled } : c))
  }

  const handleWeightChange = (key, weight) => {
    setChecks(prev => prev.map(c => c.key === key ? { ...c, weight } : c))
  }

  const handleThresholdChange = (key, value) => {
    setThresholds(prev => ({ ...prev, [key]: value }))
  }

  const handleSave = async () => {
    setStatus('saving')
    const checksPayload = {}
    const weightsPayload = {}
    for (const c of checks) {
      checksPayload[c.key] = c.enabled
      weightsPayload[c.key] = c.weight
    }
    try {
      const data = await updateConfig({
        checks: checksPayload,
        weights: weightsPayload,
        thresholds,
      })
      setChecks(data.available_checks || [])
      setThresholds(data.thresholds || {})
      setStatus('saved')
      setTimeout(() => setStatus('idle'), 2500)
    } catch (err) {
      console.error('Failed to save config', err)
      setStatus('error')
      setTimeout(() => setStatus('idle'), 3000)
    }
  }

  const saveLabel =
    status === 'saving' ? t('settings.saving') :
    status === 'saved'  ? t('settings.saved') :
    status === 'error'  ? t('settings.saveError') :
    t('settings.save')

  if (loading) {
    return (
      <div className="page-container">
        <div style={{ color: 'var(--text-muted)' }}>{t('common.loading')}</div>
      </div>
    )
  }

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t('settings.title')}</h1>
          <p className="page-subtitle">{t('settings.subtitle')}</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
            {t('settings.rerunNote')}
          </span>
          <button
            className={`btn ${status === 'error' ? 'btn-danger' : 'btn-primary'}`}
            onClick={handleSave}
            disabled={status === 'saving'}
            style={{
              minWidth: 100,
              justifyContent: 'center',
              cursor: status === 'saving' ? 'wait' : 'pointer',
              opacity: status === 'saving' ? 0.7 : 1,
            }}
          >
            {status === 'saving' && (
              <span
                style={{
                  width: 13,
                  height: 13,
                  border: '2px solid rgba(255,255,255,0.4)',
                  borderTopColor: '#fff',
                  borderRadius: '50%',
                  display: 'inline-block',
                  animation: 'spin 0.7s linear infinite',
                }}
              />
            )}
            {status === 'saved' && (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                <path d="M20 6 9 17l-5-5" />
              </svg>
            )}
            {saveLabel}
          </button>
        </div>
      </div>

      <section>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12, color: 'var(--text-primary)' }}>
          {t('settings.checksSection')}
        </h2>
        {checks.map(check => (
          <CheckCard
            key={check.key}
            check={check}
            thresholds={thresholds}
            onToggle={handleToggle}
            onWeightChange={handleWeightChange}
            onThresholdChange={handleThresholdChange}
          />
        ))}
      </section>
    </div>
  )
}
