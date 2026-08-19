import { useState, useRef, useEffect, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { fetchInvestigation, updateInvestigationStatus, addNote, addSubject, streamChat, streamReport, fetchInvestigationPrompt } from '../api/client'
import { LoadingScreen } from '../components/ui'
import ProviderSearch from '../components/ProviderSearch'
import { useLang } from '../hooks/useLang'

const STATUS_BADGE = { open: 'badge-accent', in_progress: 'badge-amber', closed: 'badge-green', archived: 'badge-red' }

export default function InvestigationDetail() {
  const { t } = useLang()
  const { id } = useParams()
  const qc = useQueryClient()
  const messagesEnd = useRef(null)
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [liveMessages, setLiveMessages] = useState([])
  const [toolStatus, setToolStatus] = useState(null)
  const [debugLog, setDebugLog] = useState([])
  const [model, setModel] = useState('claude')
  const [noteText, setNoteText] = useState('')
  const [showAddSubject, setShowAddSubject] = useState(false)
  const [newSubj, setNewSubj] = useState({ type: 'company', id: '', name: '' })
  const [reportModal, setReportModal] = useState(null)

  const { data: inv, isLoading } = useQuery({ queryKey: ['investigation', id], queryFn: () => fetchInvestigation(id) })

  const scrollBottom = useCallback(() => { messagesEnd.current?.scrollIntoView({ behavior: 'smooth' }) }, [])
  useEffect(scrollBottom, [liveMessages, inv?.chat_history?.length, scrollBottom])

  const allMessages = [...(inv?.chat_history || []), ...liveMessages]
  const pushDebug = (line) => setDebugLog(prev => [...prev.slice(-29), `${new Date().toLocaleTimeString()} ${line}`])

  const sendMessage = async () => {
    if (!input.trim() || streaming) return
    const msg = input.trim()
    setInput('')
    setStreaming(true)
    setDebugLog([])
    setLiveMessages(prev => [...prev, { role: 'user', content: msg }])
    let assistantContent = ''

    try {
      for await (const event of streamChat(id, msg, model)) {
        if (event.type === 'status') {
          if (event.stage === 'backend_request_received') {
            setToolStatus('Backend conectado, esperando modelo')
            pushDebug('backend_request_received')
          } else if (event.stage === 'waiting_model') {
            setToolStatus(`Esperando respuesta del modelo (${event.seconds || 0}s)`)
            pushDebug(`waiting_model ${event.seconds || 0}s`)
          }
        }
        else if (event.type === 'tool_use') {
          setToolStatus(t('investigationDetail.toolUsing', { tool: event.tool }))
          pushDebug(`tool_use ${event.tool}`)
        }
        else if (event.type === 'tool_result') {
          setToolStatus(t('investigationDetail.toolResults', { tool: event.tool }))
          pushDebug(`tool_result ${event.tool}`)
          if (event.tool === 'deepseek_nvidia_http' && event.result) {
            const r = event.result
            pushDebug(`http status=${r.status_code} latency=${r.latency_ms}ms req=${r.request_id_header || '-'} id=${r.response_id || '-'}`)
          } else if (event.tool === 'deepseek_nvidia' && event.result?.status === 'waiting') {
            pushDebug(`deepseek_waiting ${event.result.seconds}s`)
          }
        }
        else if (event.type === 'message') {
          setToolStatus(null)
          pushDebug(`message_chunk ${event.content?.length || 0}`)
          assistantContent += event.content
          setLiveMessages(prev => {
            const copy = [...prev]
            const last = copy[copy.length - 1]
            if (last?.role === 'assistant') { copy[copy.length - 1] = { ...last, content: assistantContent } }
            else { copy.push({ role: 'assistant', content: assistantContent }) }
            return copy
          })
        }
        else if (event.type === 'error') {
          setToolStatus(null)
          pushDebug(`error ${event.content}`)
          setLiveMessages(prev => [...prev, { role: 'assistant', content: `ERROR: ${event.content}` }])
        }
        else if (event.type === 'done') {
          setToolStatus(null)
          pushDebug('done')
        }
      }
    } catch (err) {
      pushDebug(`exception ${err.message}`)
      setLiveMessages(prev => [...prev, { role: 'assistant', content: `ERROR: ${err.message}` }])
    } finally {
      setStreaming(false)
      setLiveMessages([])
      qc.invalidateQueries({ queryKey: ['investigation', id] })
    }
  }

  const handleStatus = async (status) => {
    await updateInvestigationStatus(id, status)
    qc.invalidateQueries({ queryKey: ['investigation', id] })
  }

  const handleAddNote = async () => {
    if (!noteText.trim()) return
    await addNote(id, noteText.trim())
    setNoteText('')
    qc.invalidateQueries({ queryKey: ['investigation', id] })
  }

  const handleAddSubject = async (subject = newSubj) => {
    if (!subject.id.trim()) return
    await addSubject(id, subject)
    setNewSubj({ type: 'company', id: '', name: '' })
    setShowAddSubject(false)
    qc.invalidateQueries({ queryKey: ['investigation', id] })
  }

  const generateReport = async (type) => {
    setStreaming(true)
    let content = ''
    try {
      for await (const event of streamReport(id, type, model)) {
        if (event.type === 'content') { content += event.content; setReportModal({ type, content }) }
        else if (event.type === 'done') { qc.invalidateQueries({ queryKey: ['investigation', id] }) }
      }
    } finally { setStreaming(false) }
  }

  const handleCopyPrompt = async () => {
    try {
      const data = await fetchInvestigationPrompt(id, model)
      let textToCopy = "SYSTEM PROMPT:\n\n" + data.system_prompt + "\n\n"
      if (data.chat_history && data.chat_history.length > 0) {
        textToCopy += "CHAT HISTORY:\n\n"
        data.chat_history.forEach(msg => {
           textToCopy += `${msg.role.toUpperCase()}:\n${msg.content}\n\n`
        })
      }
      await navigator.clipboard.writeText(textToCopy)
      alert(t('investigationDetail.promptCopied', { defaultValue: 'Prompt copiado al portapapeles' }))
    } catch (err) {
      alert("Error: " + err.message)
    }
  }

  if (isLoading) return <LoadingScreen />

  return (
    <div style={{ display: 'flex', gap: 20, height: 'calc(100vh - 140px)' }}>
      {/* Chat area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {/* Header */}
        <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
          <div className="flex items-center gap-3">
            <Link to="/investigations" className="btn btn-ghost btn-sm">{t('common.back')}</Link>
            <h1 className="font-display font-bold" style={{ fontSize: '1.25rem' }}>{inv?.title}</h1>
            <span className={`badge ${STATUS_BADGE[inv?.status] || ''}`}>
              {t(`investigations.status.${inv?.status}`, { defaultValue: inv?.status?.replace('_', ' ') })}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <select className="input select" style={{ width: 130 }} value={inv?.status || 'open'} onChange={e => handleStatus(e.target.value)}>
              <option value="open">{t('investigations.status.open')}</option>
              <option value="in_progress">{t('investigations.status.in_progress')}</option>
              <option value="closed">{t('investigations.status.closed')}</option>
              <option value="archived">{t('investigations.status.archived')}</option>
            </select>
            <select className="input select" style={{ width: 180 }} value={model} onChange={e => setModel(e.target.value)}>
              <option value="claude">{t('investigationDetail.claude')}</option>
              <option value="gemini">{t('investigationDetail.gemini')}</option>
              <option value="deepseek">{t('investigationDetail.deepseek')}</option>
            </select>
            <button className="btn btn-outline btn-sm" onClick={handleCopyPrompt} title={t('investigationDetail.copyPrompt', { defaultValue: 'Copiar Prompt' })}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/></svg>
            </button>
          </div>
        </div>

        {/* Messages */}
        <div className="card" style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div className="chat-messages">
            {allMessages.length === 0 && (
              <div className="empty-state">
                <div className="empty-state-icon"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/></svg></div>
                <div className="empty-state-title">{t('investigationDetail.beginTitle')}</div>
                <div className="empty-state-text">{t('investigationDetail.beginText')}</div>
              </div>
            )}
            {allMessages.map((msg, i) => (
              <div key={i} className={`chat-bubble ${msg.role === 'user' ? 'chat-bubble-user' : 'chat-bubble-assistant'}`}>
                {msg.role === 'user' ? msg.content : <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>}
              </div>
            ))}
            {toolStatus && (
              <div className="flex items-center gap-2 text-xs text-muted" style={{ padding: '8px 0' }}>
                <div className="skeleton" style={{ width: 16, height: 16, borderRadius: '50%' }} />
                {toolStatus}
              </div>
            )}
            <div ref={messagesEnd} />
          </div>
          <div className="chat-input-area">
            <input className="input" value={input} onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && sendMessage()}
              placeholder={t('investigationDetail.messagePlaceholder')} disabled={streaming} />
            <button className="btn btn-primary" onClick={sendMessage} disabled={streaming || !input.trim()}>
              {streaming ? '…' : t('common.send')}
            </button>
          </div>
          {debugLog.length > 0 && (
            <div style={{ borderTop: '1px solid var(--border)', padding: '8px 12px', maxHeight: 120, overflowY: 'auto', fontFamily: 'monospace', fontSize: 11, color: 'var(--text-muted)', background: 'var(--bg-elevated)' }}>
              {debugLog.map((line, i) => <div key={i}>{line}</div>)}
            </div>
          )}
        </div>
      </div>

      {/* Sidebar */}
      <div style={{ width: 300, display: 'flex', flexDirection: 'column', gap: 16, overflowY: 'auto', flexShrink: 0 }}>
        {/* Subjects */}
        <div className="card card-body">
          <div className="flex items-center justify-between mb-3">
            <span className="kpi-label" style={{ margin: 0 }}>{t('investigationDetail.subjects')}</span>
            <button className="text-xs text-accent" onClick={() => setShowAddSubject(!showAddSubject)}>+</button>
          </div>
          {showAddSubject && (
            <div className="flex flex-col gap-2 mb-3" style={{ padding: 12, background: 'var(--bg-elevated)', borderRadius: 'var(--radius-md)' }}>
              <select className="input select" value={newSubj.type} onChange={e => setNewSubj({ ...newSubj, type: e.target.value })}>
                <option value="company">{t('investigationNew.subjectCompany')}</option><option value="tender">{t('investigationNew.subjectTender')}</option>
              </select>
              {newSubj.type === 'company' ? (
                <ProviderSearch
                  onSelect={({ cuit, company }) => handleAddSubject({ type: 'company', id: cuit, name: company })}
                  placeholder={t('common.searchProvider')}
                />
              ) : (
                <>
                  <input className="input" placeholder={t('investigationDetail.idOrCuit')} value={newSubj.id} onChange={e => setNewSubj({ ...newSubj, id: e.target.value })} />
                  <input className="input" placeholder={t('investigationDetail.name')} value={newSubj.name} onChange={e => setNewSubj({ ...newSubj, name: e.target.value })} />
                  <button className="btn btn-primary btn-sm" onClick={() => handleAddSubject()}>{t('common.add')}</button>
                </>
              )}
            </div>
          )}
          {(inv?.subjects || []).map((s, i) => (
            <div key={i} className="flex items-center gap-2 mb-2" style={{ padding: '8px 10px', background: 'var(--bg-elevated)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border)' }}>
              <span className="badge badge-accent" style={{ fontSize: 10 }}>{s.type?.charAt(0).toUpperCase()}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="text-sm font-semibold truncate">{s.name || s.id}</div>
                <div className="text-xs text-muted cell-mono">{s.id}</div>
              </div>
            </div>
          ))}
        </div>

        {/* Notes */}
        <div className="card card-body" style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
          <span className="kpi-label mb-3">{t('investigationDetail.intelligenceLog')}</span>
          <div className="mb-3 flex gap-2">
            <input className="input" value={noteText} onChange={e => setNoteText(e.target.value)} placeholder={t('investigationDetail.recordFindings')} style={{ flex: 1 }} />
            <button className="btn btn-ghost btn-sm" onClick={handleAddNote}>{t('common.add')}</button>
          </div>
          <div style={{ flex: 1, overflowY: 'auto' }} className="flex flex-col gap-2">
            {(inv?.notes || []).map(n => (
              <div key={n.id} style={{ padding: '10px 12px', background: 'var(--bg-elevated)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border)' }}>
                <div className="text-sm" style={{ whiteSpace: 'pre-wrap' }}>{n.text}</div>
                <div className="text-xs text-muted mt-1">{n.created_at?.slice(0, 16)}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Reports */}
        <div className="card card-body">
          <span className="kpi-label mb-3">{t('investigationDetail.reports')}</span>
          <div className="flex flex-col gap-2 mb-3">
            {['executive_summary', 'timeline', 'network_analysis', 'cartel_hypothesis'].map(reportType => (
              <button key={reportType} className="btn btn-ghost btn-sm" style={{ justifyContent: 'flex-start' }}
                onClick={() => generateReport(reportType)} disabled={streaming}>
                {t(`investigationDetail.reportTypes.${reportType}`)}
              </button>
            ))}
          </div>
          {(inv?.reports || []).map(r => (
            <div key={r.id} className="card-glow" onClick={() => setReportModal({ type: r.type, content: r.content })}
              style={{ padding: '8px 12px', background: 'var(--bg-elevated)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border)', cursor: 'pointer', marginBottom: 8 }}>
              <div className="text-sm font-semibold" style={{ textTransform: 'capitalize' }}>{r.type?.replace(/_/g, ' ')}</div>
              <div className="text-xs text-muted">{r.created_at?.slice(0, 16)}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Report Modal */}
      {reportModal && (
        <div className="modal-overlay" onClick={() => setReportModal(null)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <span className="font-display font-bold" style={{ textTransform: 'capitalize' }}>{reportModal.type?.replace(/_/g, ' ')}</span>
              <button className="btn btn-ghost btn-sm" onClick={() => setReportModal(null)}>✕</button>
            </div>
            <div className="modal-body chat-bubble-assistant">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{reportModal.content}</ReactMarkdown>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}



