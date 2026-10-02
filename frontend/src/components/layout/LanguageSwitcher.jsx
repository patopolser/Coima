import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'

const LANGUAGES = [
  { code: 'es', labelKey: 'language.es' },
  { code: 'en', labelKey: 'language.en' },
]

export default function LanguageSwitcher() {
  const { i18n, t } = useTranslation()
  const qc = useQueryClient()
  const current = i18n.language === 'es' ? 'es' : 'en'

  const setLang = (lang) => {
    if (lang === current) return
    i18n.changeLanguage(lang)
    // Check labels and descriptions are localized server-side.
    qc.invalidateQueries()
  }

  return (
    <div className="lang-switch" role="group" aria-label={t('language.ariaLabel')}>
      {LANGUAGES.map(({ code, labelKey }) => (
        <button
          key={code}
          type="button"
          onClick={() => setLang(code)}
          aria-label={t(labelKey)}
          aria-pressed={current === code}
          title={t(labelKey)}
        >
          {code.toUpperCase()}
        </button>
      ))}
    </div>
  )
}
