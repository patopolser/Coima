import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Crescent } from '../components/brand'
import { Reveal } from '../motion'
import { IconArrowRight, IconSearch } from '../components/icons'

export default function NotFound() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  return (
    <Reveal className="not-found">
      <div data-reveal="1"><Crescent /></div>
      <h1 className="page-title" data-reveal="2">{t('notFound.title')}</h1>
      <p className="secondary" data-reveal="2">{t('notFound.text')}</p>
      <div className="not-found-actions" data-reveal="3">
        <button type="button" className="btn btn-primary" onClick={() => navigate('/')}>
          {t('notFound.home')} <IconArrowRight />
        </button>
        <button type="button" className="btn btn-secondary" onClick={() => navigate('/providers?focus=search')}>
          <IconSearch /> {t('notFound.search')}
        </button>
      </div>
    </Reveal>
  )
}
