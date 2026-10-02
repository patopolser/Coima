import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

// Contact for right of reply / correction / takedown (DISCLAIMER.md section 6).
const RECTIFICATION_EMAIL = 'polserpatricio@gmail.com'

export default function Footer() {
  const { t } = useTranslation()
  return (
    <footer className="footer" role="contentinfo">
      <Link to="/terms">{t('footer.terms')}</Link>
      <span className="footer-sep" aria-hidden="true">·</span>
      <a href={`mailto:${RECTIFICATION_EMAIL}?subject=${encodeURIComponent(t('footer.rectifySubject'))}`}>
        {t('footer.rectify')}
      </a>
    </footer>
  )
}
