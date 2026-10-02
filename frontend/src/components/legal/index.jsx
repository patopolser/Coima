import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { DUR, EASE, Disclosure, play, scaleIn, shine, usePresence, useGlassPointer } from '../../motion'
import { readAcceptance, writeAcceptance, TERMS_VERSION } from '../../legal/terms'
import { Wordmark } from '../brand'
import { InfoTip } from '../ui'
import { useToast } from '../ui/Toast'
import { IconArrowRight, IconChevronDown } from '../icons'
import LanguageSwitcher from '../layout/LanguageSwitcher'

// Routes readable before accepting (the terms themselves).
const PUBLIC_PATHS = ['/terms']

// Five-point summary: short title + one line each.
export function TermsSummary() {
  const { t } = useTranslation()
  const items = t('terms.items', { returnObjects: true })
  return (
    <ol className="terms-list">
      {(Array.isArray(items) ? items : []).map((item, i) => (
        <li key={item.title}>
          <span className="terms-num">{i + 1}</span>
          <span className="terms-item-title">{item.title}</span>
          <span className="terms-item-text">{item.text}</span>
        </li>
      ))}
    </ol>
  )
}

// Full legal text, sectioned. Mirrors DISCLAIMER.md.
export function TermsFullText() {
  const { t } = useTranslation()
  const sections = t('terms.full', { returnObjects: true })
  return (
    <div className="legal-text">
      {(Array.isArray(sections) ? sections : []).map(s => (
        <section key={s.title}>
          <h3>{s.title}</h3>
          <p>{s.text}</p>
        </section>
      ))}
    </div>
  )
}

// Keeps Tab / Shift+Tab inside `ref` while mounted.
function useFocusTrap(ref) {
  useEffect(() => {
    const el = ref.current
    if (!el) return undefined
    const onKey = e => {
      if (e.key !== 'Tab') return
      const items = [...el.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])')]
      if (!items.length) return
      const first = items[0]
      const last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
    el.addEventListener('keydown', onKey)
    return () => el.removeEventListener('keydown', onKey)
  }, [ref])
}

function TermsDialog({ onAccept }) {
  const { t } = useTranslation()
  const [checked, setChecked] = useState(false)
  const [showFull, setShowFull] = useState(false)
  const [denied, setDenied] = useState(false)
  const panelRef = useRef(null)
  useFocusTrap(panelRef)
  useGlassPointer(panelRef)

  useLayoutEffect(() => {
    const el = panelRef.current
    const a = scaleIn(el)
    const s = shine(el)
    el?.focus({ preventScroll: true })
    return () => { a?.cancel(); s?.cancel() }
  }, [])

  return (
    <div
      ref={panelRef}
      className="modal glass glass-strong glass-clip"
      role="dialog"
      aria-modal="true"
      aria-labelledby="terms-title"
      tabIndex={-1}
      style={{ outline: 'none' }}
    >
      <div className="terms-head">
        <Wordmark />
        <LanguageSwitcher />
      </div>

      {denied ? (
        <div className="gate-denied">
          <h2 id="terms-title" className="terms-title" style={{ marginBottom: 0 }}>{t('terms.deniedTitle')}</h2>
          <p className="secondary">{t('terms.deniedText')}</p>
          <button type="button" className="btn btn-secondary" onClick={() => setDenied(false)}>
            {t('terms.back')}
          </button>
        </div>
      ) : (
        <>
          <h2 id="terms-title" className="terms-title">{t('terms.title')}</h2>
          <TermsSummary />

          <button
            type="button"
            className="terms-full-toggle"
            aria-expanded={showFull}
            aria-controls="terms-full"
            onClick={() => setShowFull(v => !v)}
          >
            {t('terms.readFull')} <IconChevronDown size={14} />
          </button>
          <Disclosure open={showFull} id="terms-full">
            <div className="terms-full"><TermsFullText /></div>
          </Disclosure>

          <label className="check terms-accept">
            <input type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)} />
            {t('terms.checkbox')}
          </label>

          <div className="terms-actions">
            <button type="button" className="btn btn-ghost" onClick={() => setDenied(true)}>
              {t('terms.decline')}
            </button>
            <button type="button" className="btn btn-primary" disabled={!checked} onClick={onAccept}>
              {t('terms.accept')} <IconArrowRight />
            </button>
          </div>
          <p className="terms-meta">{t('terms.meta', { version: TERMS_VERSION })}</p>
        </>
      )}
    </div>
  )
}

// Static silhouette of the panel shown blurred behind the terms dialog.
function GateBackdrop() {
  return (
    <div className="gate-backdrop" aria-hidden="true">
      <div className="skeleton" style={{ width: 160, height: 32 }} />
      <div className="skeleton" style={{ height: 96, borderRadius: 20 }} />
      <div className="dash-grid">
        <div className="skeleton" style={{ height: 360, borderRadius: 20 }} />
        <div className="skeleton" style={{ height: 360, borderRadius: 20 }} />
      </div>
    </div>
  )
}

/*
 * Blocking terms gate. Until the current TERMS_VERSION is accepted, no page
 * mounts (so no data is fetched); Escape and outside clicks do nothing.
 */
export function TermsGate({ children }) {
  const { t } = useTranslation()
  const { pathname } = useLocation()
  const toast = useToast()
  const [accepted, setAccepted] = useState(() => !!readAcceptance())
  const isPublic = PUBLIC_PATHS.includes(pathname)
  const blocking = !accepted && !isPublic

  const { mounted, ref } = usePresence(blocking, {
    onEnter: el => play(el, [{ opacity: 0 }, { opacity: 1 }], { duration: DUR.modalIn, easing: EASE.in }),
    onExit: el => play(el, [{ opacity: 1 }, { opacity: 0 }], { duration: DUR.modalOut, easing: EASE.out, fill: 'forwards' }),
  })

  const accept = () => {
    const { saved } = writeAcceptance()
    setAccepted(true)
    if (!saved) toast(t('terms.notSaved'), { kind: 'error', duration: 8000 })
  }

  return (
    <>
      {blocking ? <GateBackdrop /> : children}
      {mounted && (
        <div ref={ref} className="modal-overlay">
          <TermsDialog onAccept={accept} />
        </div>
      )}
    </>
  )
}

/*
 * The one legal sentence next to a score: automated indicator, not an
 * accusation. The (i) gives the longer reading and links to the terms.
 */
export function RiskCaveat({ onDark = false }) {
  const { t } = useTranslation()
  return (
    <span className={`score-caveat ${onDark ? 'on-focus' : ''}`}>
      {t('risk.caveat')}
      <InfoTip label={t('risk.caveatLabel')} align="end">
        {t('risk.caveatLong')}{' '}
        <Link to="/terms">{t('terms.link')}</Link>
      </InfoTip>
    </span>
  )
}
