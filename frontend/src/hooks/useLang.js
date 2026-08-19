import { useTranslation } from 'react-i18next'

export function useLang() {
  const { t, i18n } = useTranslation()
  const lang = i18n.language === 'es' ? 'es' : 'en'
  const locale = lang === 'es' ? 'es-AR' : 'en-US'
  return { t, lang, locale, i18n }
}
