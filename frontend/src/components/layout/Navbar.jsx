import { NavLink, Link, useLocation, useNavigate } from 'react-router-dom'
import { useState, useRef, useLayoutEffect, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import LanguageSwitcher from './LanguageSwitcher'
import { Wordmark } from '../brand'
import { Menu, MenuItem } from '../ui'
import { usePresence, useGlassPointer } from '../../motion'
import {
  IconPanel, IconBuilding, IconLandmark, IconUser, IconNetwork,
  IconSearch, IconMore, IconServer, IconSettings, IconMenu, IconClose,
} from '../icons'

// Investigation views. Operational tools (scraper, settings) live in the "…" menu.
const NAV = [
  { to: '/', labelKey: 'nav.dashboard', Icon: IconPanel, exact: true },
  { to: '/providers', labelKey: 'nav.providers', Icon: IconBuilding, also: ['/companies', '/checks'] },
  { to: '/units', labelKey: 'nav.units', Icon: IconLandmark },
  { to: '/authorizers', labelKey: 'nav.authorizers', Icon: IconUser },
  { to: '/graph', labelKey: 'nav.graph', Icon: IconNetwork },
]

function isActive(link, pathname) {
  if (link.exact) return pathname === link.to
  return [link.to, ...(link.also || [])].some(p => pathname.startsWith(p))
}

export default function Navbar() {
  const { t } = useTranslation()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const [mobileOpen, setMobileOpen] = useState(false)
  const barRef = useRef(null)
  const linkRefs = useRef({})
  const [indicator, setIndicator] = useState({ left: 0, top: 0, width: 0, height: 0, visible: false })
  const mobile = usePresence(mobileOpen)
  useGlassPointer(barRef)

  const active = NAV.find(l => isActive(l, pathname))

  // Sliding indicator under the active link.
  useLayoutEffect(() => {
    const update = () => {
      const el = active ? linkRefs.current[active.to] : null
      if (el && el.offsetParent) {
        setIndicator({ left: el.offsetLeft, top: el.offsetTop, width: el.offsetWidth, height: el.offsetHeight, visible: true })
      } else {
        setIndicator(i => ({ ...i, visible: false }))
      }
    }
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [active, t])

  useEffect(() => { setMobileOpen(false) }, [pathname])

  return (
    <div className="navbar-shell">
      <header ref={barRef} className="navbar glass">
        <Link to="/" className="navbar-brand" aria-label={t('nav.home')}>
          <Wordmark />
        </Link>

        <nav className="nav-links" aria-label={t('nav.main')}>
          <span
            className="nav-indicator"
            aria-hidden="true"
            style={{
              transform: `translate(${indicator.left}px, ${indicator.top}px)`,
              width: indicator.width,
              height: indicator.height,
              opacity: indicator.visible ? 1 : 0,
            }}
          />
          {NAV.map(link => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.exact}
              ref={el => { linkRefs.current[link.to] = el }}
              className={`nav-link ${active === link ? 'active' : ''}`}
              aria-current={active === link ? 'page' : undefined}
              title={t(link.labelKey)}
            >
              <link.Icon size={16} />
              <span className="nav-label">{t(link.labelKey)}</span>
            </NavLink>
          ))}
        </nav>

        <div className="navbar-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => navigate('/providers?focus=search')}
          >
            <IconSearch /> <span className="nav-label">{t('nav.search')}</span>
          </button>
          <LanguageSwitcher />
          <Menu label={t('nav.more')} icon={<IconMore size={18} />}>
            <MenuItem icon={<IconServer />} onClick={() => navigate('/scraper')}>{t('nav.scraper')}</MenuItem>
            <MenuItem icon={<IconSettings />} onClick={() => navigate('/settings')}>{t('nav.settings')}</MenuItem>
          </Menu>
          <button
            type="button"
            className="btn btn-ghost btn-icon navbar-mobile-toggle"
            aria-label={mobileOpen ? t('nav.closeMenu') : t('nav.openMenu')}
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen(o => !o)}
          >
            {mobileOpen ? <IconClose size={18} /> : <IconMenu size={18} />}
          </button>
        </div>
      </header>

      {mobile.mounted && (
        <nav ref={mobile.ref} className="navbar-mobile glass glass-strong" aria-label={t('nav.main')}>
          {NAV.map(link => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.exact}
              className={`nav-link ${active === link ? 'active' : ''}`}
            >
              <link.Icon size={16} />
              {t(link.labelKey)}
            </NavLink>
          ))}
        </nav>
      )}
    </div>
  )
}
