import { useEffect, useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchConfig, updateConfig } from '../api/client'
import { LoadingScreen, ErrorState, Switch, InfoTip } from '../components/ui'
import { useToast } from '../components/ui/Toast'
import { Reveal, Disclosure } from '../motion'
import { IconCheck, IconChevronDown } from '../components/icons'

// Threshold keys are snake_case backend identifiers; show them as words.
const humanize = key => key.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase())

function CheckRow({ check, thresholds, onToggle, onWeightChange, onThresholdChange }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const thresholdEntries = Object.entries(check.check_thresholds || {})
  const hasDetail = !!check.description || thresholdEntries.length > 0
  const detailId = `setting-${check.key}`

  return (
    <div className="setting-row">
      <div className="setting-main">
        <span className={`setting-name ${check.enabled ? '' : 'off'}`}>{check.label}</span>
        <label className="setting-weight">
          {t('settings.weight')}
          <input
            type="number"
            min={0}
            max={100}
            className="input input-sm tabular"
            value={check.weight}
            onChange={e => onWeightChange(check.key, Number(e.target.value))}
            title={t('settings.defaultWeight', { value: check.default_weight })}
          />
        </label>
        <Switch
          checked={!!check.enabled}
          onChange={v => onToggle(check.key, v)}
          label={t(check.enabled ? 'settings.disable' : 'settings.enable', { name: check.label })}
        />
        {hasDetail ? (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            aria-expanded={open}
            aria-controls={detailId}
            onClick={() => setOpen(o => !o)}
          >
            {t('settings.configure')}
            <IconChevronDown size={14} style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform var(--dur-hover) var(--ease-in)' }} />
          </button>
        ) : <span />}
      </div>
      <Disclosure open={open} id={detailId}>
        <div className="setting-detail">
          {check.description && <p className="setting-desc">{check.description}</p>}
          {thresholdEntries.length > 0 && (
            <div className="setting-thresholds">
              {thresholdEntries.map(([key, defaultVal]) => (
                <label key={key}>
                  {humanize(key)}
                  <input
                    type="number"
                    step="any"
                    className="input input-sm tabular"
                    value={thresholds[key] ?? defaultVal}
                    title={t('settings.defaultWeight', { value: defaultVal })}
                    onChange={e => {
                      const raw = e.target.value
                      const num = raw.includes('.') ? parseFloat(raw) : parseInt(raw, 10)
                      onThresholdChange(key, Number.isNaN(num) ? raw : num)
                    }}
                  />
                </label>
              ))}
            </div>
          )}
        </div>
      </Disclosure>
    </div>
  )
}

export default function Settings() {
  const { t, i18n } = useTranslation()
  const toast = useToast()
  const [checks, setChecks] = useState([])
  const [thresholds, setThresholds] = useState({})
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)

  const load = useCallback(async () => {
    setLoadError(null)
    try {
      const data = await fetchConfig()
      setChecks(data.available_checks || [])
      setThresholds(data.thresholds || {})
      setDirty(false)
    } catch (err) {
      setLoadError(err)
    } finally {
      setLoading(false)
    }
  }, [])

  // Re-fetch when the UI language changes: labels and descriptions are
  // localized server-side via Accept-Language.
  useEffect(() => { load() }, [load, i18n.language])

  const patchCheck = (key, patch) => {
    setChecks(prev => prev.map(c => (c.key === key ? { ...c, ...patch } : c)))
    setDirty(true)
  }

  const handleSave = async () => {
    setSaving(true)
    const checksPayload = {}
    const weightsPayload = {}
    for (const c of checks) {
      checksPayload[c.key] = c.enabled
      weightsPayload[c.key] = c.weight
    }
    try {
      const data = await updateConfig({ checks: checksPayload, weights: weightsPayload, thresholds })
      setChecks(data.available_checks || [])
      setThresholds(data.thresholds || {})
      setDirty(false)
      toast(t('settings.saved'), { kind: 'success' })
    } catch (err) {
      toast(`${t('settings.saveError')}: ${err.detail || err.message}`)
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <LoadingScreen />
  if (loadError) return <ErrorState error={loadError} onRetry={load} />

  return (
    <Reveal>
      <div className="page-head">
        <h1 className="page-title">{t('settings.title')}</h1>
        <InfoTip>{t('settings.rerunNote')}</InfoTip>
        <div className="page-head-actions">
          <button type="button" className="btn btn-primary" onClick={handleSave} disabled={saving || !dirty}>
            <IconCheck /> {saving ? t('settings.saving') : t('settings.save')}
          </button>
        </div>
      </div>

      <section className="card" data-reveal="1" aria-label={t('settings.detectors')}>
        {checks.map(check => (
          <CheckRow
            key={check.key}
            check={check}
            thresholds={thresholds}
            onToggle={(key, enabled) => patchCheck(key, { enabled })}
            onWeightChange={(key, weight) => patchCheck(key, { weight })}
            onThresholdChange={(key, value) => { setThresholds(prev => ({ ...prev, [key]: value })); setDirty(true) }}
          />
        ))}
      </section>
    </Reveal>
  )
}
