import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './locales/en.json'
import es from './locales/es.json'

export const LANG_KEY = 'coima_lang'

// Storage can be unavailable (private mode, blocked site data).
const safeGet = key => { try { return localStorage.getItem(key) } catch { return null } }
const safeSet = (key, value) => { try { localStorage.setItem(key, value) } catch { /* session only */ } }

const stored = safeGet(LANG_KEY)
const lng = stored === 'es' ? 'es' : 'en'

i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    es: { translation: es },
  },
  lng,
  fallbackLng: 'en',
  supportedLngs: ['en', 'es'],
  interpolation: { escapeValue: false },
})

i18n.on('languageChanged', (lang) => {
  safeSet(LANG_KEY, lang)
  document.documentElement.lang = lang
})

document.documentElement.lang = lng

export function getApiLanguage() {
  return i18n.language || safeGet(LANG_KEY) || 'en'
}

export default i18n
