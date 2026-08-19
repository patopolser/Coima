import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { FlagAR, FlagUS } from '../icons'

const LANGUAGES = [
  { code: 'en', Flag: FlagUS, labelKey: 'language.en' },
  { code: 'es', Flag: FlagAR, labelKey: 'language.es' },
]

export default function LanguageSwitcher() {
  const { i18n, t } = useTranslation()
  const qc = useQueryClient()
  const current = i18n.language === 'es' ? 'es' : 'en'

  const setLang = (lang) => {
    if (lang === current) return
    i18n.changeLanguage(lang)
    qc.invalidateQueries()
  }

  return (
    <div className="lang-switcher" role="group" aria-label={t('language.ariaLabel')}>
      {LANGUAGES.map(({ code, Flag, labelKey }) => (
        <button
          key={code}
          type="button"
          className={`lang-switcher-btn ${current === code ? 'active' : ''}`}
          onClick={() => setLang(code)}
          aria-label={t(labelKey)}
          aria-pressed={current === code}
          title={t(labelKey)}
        >
          <Flag size={20} />
        </button>
      ))}
    </div>
  )
}
