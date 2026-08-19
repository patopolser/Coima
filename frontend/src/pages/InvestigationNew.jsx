import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createInvestigation } from '../api/client'
import ProviderSearch from '../components/ProviderSearch'
import { useLang } from '../hooks/useLang'

export default function InvestigationNew() {
  const { t } = useLang()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const qc = useQueryClient()

  const [title, setTitle] = useState('')
  const [subjects, setSubjects] = useState(() => {
    const t = searchParams.get('subject_type')
    const id = searchParams.get('subject_id')
    if (t && id) return [{ type: t, id, name: searchParams.get('subject_name') || '' }]
    return []
  })
  const [newType, setNewType] = useState('company')
  const [newId, setNewId] = useState('')
  const [newName, setNewName] = useState('')

  const mutation = useMutation({
    mutationFn: createInvestigation,
    onSuccess: (inv) => {
      qc.invalidateQueries({ queryKey: ['investigations'] })
      navigate(`/investigations/${inv.id}`)
    },
  })

  const addSubject = () => {
    if (!newId.trim()) return
    setSubjects([...subjects, { type: newType, id: newId.trim(), name: newName.trim() }])
    setNewId(''); setNewName('')
  }

  const addCompanySubject = ({ cuit, company }) => {
    if (!cuit.trim()) return
    setSubjects([...subjects, { type: 'company', id: cuit.trim(), name: company || '' }])
  }

  const submit = () => {
    if (!title.trim()) return
    mutation.mutate({ title: title.trim(), subjects, context_snapshot: {} })
  }

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">{t('investigationNew.title')}</h1>
        <p className="page-subtitle">{t('investigationNew.subtitle')}</p>
      </div>

      <div className="card card-body" style={{ maxWidth: 640 }}>
        <div className="mb-6">
          <label className="kpi-label mb-2" style={{ display: 'block' }}>{t('investigationNew.titleLabel')}</label>
          <input className="input" value={title} onChange={e => setTitle(e.target.value)} placeholder={t('investigationNew.titlePlaceholder')} />
        </div>

        <div className="mb-6">
          <label className="kpi-label mb-2" style={{ display: 'block' }}>{t('investigationNew.subjectsLabel')}</label>
          {subjects.length > 0 && (
            <div className="flex flex-col gap-2 mb-4">
              {subjects.map((s, i) => (
                <div key={i} className="flex items-center gap-3" style={{ padding: '8px 12px', background: 'var(--bg-elevated)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border)' }}>
                  <span className="badge badge-accent">{s.type}</span>
                  <span className="cell-mono text-sm">{s.id}</span>
                  {s.name && <span className="text-sm text-secondary">{s.name}</span>}
                  <button className="text-xs text-muted" style={{ marginLeft: 'auto' }} onClick={() => setSubjects(subjects.filter((_, j) => j !== i))}>✕</button>
                </div>
              ))}
            </div>
          )}
          <div className="flex gap-2 flex-wrap">
            <select className="input select" style={{ width: 120 }} value={newType} onChange={e => setNewType(e.target.value)}>
              <option value="company">{t('investigationNew.subjectCompany')}</option>
              <option value="tender">{t('investigationNew.subjectTender')}</option>
            </select>
            {newType === 'company' ? (
              <ProviderSearch
                onSelect={addCompanySubject}
                placeholder={t('common.searchProvider')}
                style={{ flex: 1, minWidth: 200 }}
              />
            ) : (
              <>
                <input className="input" style={{ flex: 1 }} value={newId} onChange={e => setNewId(e.target.value)} placeholder={t('investigationNew.idPlaceholder')} />
                <input className="input" style={{ flex: 1 }} value={newName} onChange={e => setNewName(e.target.value)} placeholder={t('investigationNew.nameOptional')} />
                <button className="btn btn-ghost btn-sm" onClick={addSubject}>{t('common.add')}</button>
              </>
            )}
          </div>
        </div>

        <button className="btn btn-primary" onClick={submit} disabled={mutation.isPending}>
          {mutation.isPending ? t('investigationNew.creating') : t('investigationNew.create')}
        </button>
      </div>
    </>
  )
}
