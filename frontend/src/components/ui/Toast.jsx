import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { usePresence } from '../../motion'
import { IconAlert, IconCheck, IconClose } from '../icons'

const ToastContext = createContext(() => {})

// App-wide transient message (errors, confirmations). Replaces alert().
export function ToastProvider({ children }) {
  const [toast, setToast] = useState(null)
  const timer = useRef(0)

  const show = useCallback((message, { kind = 'error', duration = 5000 } = {}) => {
    clearTimeout(timer.current)
    setToast({ message, kind, id: Date.now() })
    timer.current = setTimeout(() => setToast(null), duration)
  }, [])

  useEffect(() => () => clearTimeout(timer.current), [])

  return (
    <ToastContext.Provider value={show}>
      {children}
      <ToastView toast={toast} onClose={() => setToast(null)} />
    </ToastContext.Provider>
  )
}

export function useToast() {
  return useContext(ToastContext)
}

function ToastView({ toast, onClose }) {
  const { t } = useTranslation()
  const last = useRef(toast)
  if (toast) last.current = toast
  const { mounted, ref } = usePresence(!!toast)
  const shown = toast || last.current
  if (!mounted || !shown) return null
  return (
    <div ref={ref} className={`toast toast-${shown.kind} glass glass-strong`} role={shown.kind === 'error' ? 'alert' : 'status'}>
      {shown.kind === 'error' ? <IconAlert /> : <IconCheck />}
      <span>{shown.message}</span>
      <button type="button" className="btn btn-ghost btn-icon btn-sm" onClick={onClose} aria-label={t('common.close')}>
        <IconClose size={14} />
      </button>
    </div>
  )
}
