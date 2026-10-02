import { useRef } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Navbar from './components/layout/Navbar'
import Footer from './components/layout/Footer'
import { TermsGate } from './components/legal'
import { ToastProvider } from './components/ui/Toast'
import { PageTransition } from './motion'
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
import Terms from './pages/Terms'
import NotFound from './pages/NotFound'

export default function App() {
  const mainRef = useRef(null)
  return (
    <BrowserRouter>
      <ToastProvider>
        <div className="app">
          <Navbar />
          <main ref={mainRef} className="main" tabIndex={-1}>
            {/* Nothing mounts (or fetches) until the current terms are accepted. */}
            <TermsGate>
              <PageTransition mainRef={mainRef}>
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
                  <Route path="/terms" element={<Terms />} />
                  <Route path="*" element={<NotFound />} />
                </Routes>
              </PageTransition>
            </TermsGate>
          </main>
          <Footer />
        </div>
      </ToastProvider>
    </BrowserRouter>
  )
}
