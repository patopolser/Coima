import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import Navbar from './components/layout/Navbar'
import DisclaimerBanner from './components/layout/DisclaimerBanner'
import Dashboard from './pages/Dashboard'
import Providers from './pages/Providers'
import CheckDetail from './pages/CheckDetail'
import CompanyDetail from './pages/CompanyDetail'
import Units from './pages/Units'
import UnitDetail from './pages/UnitDetail'
import Authorizers from './pages/Authorizers'
import AuthorizerDetail from './pages/AuthorizerDetail'
import GraphExplorer from './pages/GraphExplorer'
import Scraper from './pages/Scraper'
import Settings from './pages/Settings'

// Permanent legal footer on every page: results are heuristic indicators, not
// accusations. Complements DisclaimerBanner and the per-page LegalNote.
// See DISCLAIMER.md.
function LegalFooter() {
  const { t } = useTranslation()
  return (
    <footer role="contentinfo" style={{
      padding: '12px 24px', fontSize: 12, color: 'var(--text-muted)',
      textAlign: 'center', borderTop: '1px solid var(--border)', lineHeight: 1.5,
    }}>
      {t('disclaimer.footer')}{' '}
      <a
        href="https://github.com/patopolser/Coima/blob/main/DISCLAIMER.md"
        target="_blank"
        rel="noopener noreferrer"
        style={{ color: 'inherit', textDecoration: 'underline' }}
      >
        {t('disclaimer.link')}
      </a>
    </footer>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="app-layout">
        <Navbar />
        <DisclaimerBanner />
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/providers" element={<Providers />} />
            <Route path="/checks/:key" element={<CheckDetail />} />
            <Route path="/companies/:cuit" element={<CompanyDetail />} />
            <Route path="/units" element={<Units />} />
            {/* Code is base64url-encoded (see utils/ids) so UOC codes with
                slashes fit a single path segment. */}
            <Route path="/units/:code" element={<UnitDetail />} />
            <Route path="/authorizers" element={<Authorizers />} />
            <Route path="/authorizers/:name" element={<AuthorizerDetail />} />
            <Route path="/graph" element={<GraphExplorer />} />
            <Route path="/scraper" element={<Scraper />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
        <LegalFooter />
      </div>
    </BrowserRouter>
  )
}
