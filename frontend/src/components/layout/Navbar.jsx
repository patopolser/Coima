import { NavLink, useLocation } from 'react-router-dom'
import { useState, useRef, useLayoutEffect } from 'react'
import { useTranslation } from 'react-i18next'
import LanguageSwitcher from './LanguageSwitcher'

const navLinks = [
  { to: '/providers', labelKey: 'nav.providers' },
  { to: '/units', labelKey: 'nav.units' },
  { to: '/authorizers', labelKey: 'nav.authorizers' },
  { to: '/investigations', labelKey: 'nav.investigations' },
  { to: '/graph', labelKey: 'nav.graph' },
  { to: '/scraper', labelKey: 'nav.scraper' },
  { to: '/settings', labelKey: 'nav.settings' },
]

export default function Navbar() {
  const { t } = useTranslation()
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()
  const linkRefs = useRef({})
  const [indicator, setIndicator] = useState({ left: 0, top: 0, width: 0, height: 0, visible: false })

  const isActive = (link) => {
    if (link.exact) return location.pathname === link.to
    return location.pathname.startsWith(link.to)
  }

  const activeLink = navLinks.find(isActive)

  useLayoutEffect(() => {
    const update = () => {
      const el = activeLink ? linkRefs.current[activeLink.to] : null
      if (el) {
        setIndicator({ left: el.offsetLeft, top: el.offsetTop, width: el.offsetWidth, height: el.offsetHeight, visible: true })
      } else {
        setIndicator(i => ({ ...i, visible: false }))
      }
    }
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [activeLink, t])

  return (
    <header className="navbar">
      <div className="navbar-inner">
        <NavLink to="/" className="navbar-brand">
          <div className="navbar-brand-icon">C</div>
          <span>Coima</span>
        </NavLink>

        <nav className="navbar-nav">
          <span
            className="nav-indicator"
            style={{
              transform: `translate(${indicator.left}px, ${indicator.top}px)`,
              width: indicator.width,
              height: indicator.height,
              opacity: indicator.visible ? 1 : 0,
            }}
          />
          {navLinks.map(link => (
            <NavLink
              key={link.to}
              to={link.to}
              ref={el => { linkRefs.current[link.to] = el }}
              className={`nav-link ${isActive(link) ? 'active' : ''}`}
            >
              {t(link.labelKey)}
            </NavLink>
          ))}
        </nav>

        <div className="navbar-actions">
          <LanguageSwitcher />
          <button
            className="mobile-nav btn-ghost btn-sm"
            onClick={() => setMobileOpen(!mobileOpen)}
          >
            ☰
          </button>
        </div>
      </div>

      {mobileOpen && (
        <nav className="navbar-mobile">
          {navLinks.map(link => (
            <NavLink
              key={link.to}
              to={link.to}
              className={`nav-link ${isActive(link) ? 'active' : ''}`}
              onClick={() => setMobileOpen(false)}
            >
              {t(link.labelKey)}
            </NavLink>
          ))}
        </nav>
      )}
    </header>
  )
}
