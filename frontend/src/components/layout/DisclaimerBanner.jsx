import { useState } from 'react'
import { useTranslation } from 'react-i18next'

const STORAGE_KEY = 'coima.disclaimerDismissed'

// Persistent, dismissible banner reminding users that detection results are
// heuristic indicators over public data, not accusations. See DISCLAIMER.md.
export default function DisclaimerBanner() {
  const { t } = useTranslation()
  const [dismissed, setDismissed] = useState(
    () => localStorage.getItem(STORAGE_KEY) === '1'
  )

  if (dismissed) return null

  const dismiss = () => {
    localStorage.setItem(STORAGE_KEY, '1')
    setDismissed(true)
  }

  return (
    <div role="note" className="disclaimer-banner" style={styles.banner}>
      <span style={styles.text}>{t('disclaimer.text')}</span>
      <a
        href="https://github.com/patopolser/Coima/blob/main/DISCLAIMER.md"
        target="_blank"
        rel="noopener noreferrer"
        style={styles.link}
      >
        {t('disclaimer.link')}
      </a>
      <button type="button" onClick={dismiss} style={styles.dismiss}>
        {t('disclaimer.dismiss')}
      </button>
    </div>
  )
}

const styles = {
  banner: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.75rem',
    padding: '0.5rem 1rem',
    fontSize: '0.85rem',
    background: '#3a2f00',
    color: '#ffe08a',
    borderBottom: '1px solid #5a4a00',
  },
  text: { flex: 1 },
  link: { color: '#ffe08a', textDecoration: 'underline', whiteSpace: 'nowrap' },
  dismiss: {
    background: 'transparent',
    border: '1px solid currentColor',
    color: 'inherit',
    borderRadius: '4px',
    padding: '0.15rem 0.6rem',
    cursor: 'pointer',
    whiteSpace: 'nowrap',
  },
}
