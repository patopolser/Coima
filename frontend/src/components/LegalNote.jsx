import { useTranslation } from 'react-i18next'

// Inline legal reminder rendered under the header of every page that shows
// scores or findings: results are heuristic indicators, not accusations.
// Complements the top DisclaimerBanner and the layout's legal footer so the
// notice stays visible next to the data itself. See DISCLAIMER.md.
export default function LegalNote() {
  const { t } = useTranslation()
  return (
    <p role="note" style={{ fontSize: 12, color: 'var(--text-muted)', margin: '6px 0 0', fontStyle: 'italic' }}>
      {t('disclaimer.short')}
    </p>
  )
}
