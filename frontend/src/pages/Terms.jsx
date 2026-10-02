import { useTranslation } from 'react-i18next'
import { TermsSummary, TermsFullText } from '../components/legal'
import { Reveal } from '../motion'
import { TERMS_VERSION } from '../legal/terms'

// Public page: readable before accepting, linked from the footer and caveats.
export default function Terms() {
  const { t } = useTranslation()
  return (
    <Reveal className="legal-page stack">
      <div className="page-head" data-reveal="1" style={{ marginBottom: 0 }}>
        <h1 className="page-title">{t('terms.title')}</h1>
        <span className="chip">{t('terms.version', { version: TERMS_VERSION })}</span>
      </div>
      <div className="card card-pad" data-reveal="2"><TermsSummary /></div>
      <div className="card card-pad" data-reveal="3"><TermsFullText /></div>
    </Reveal>
  )
}
