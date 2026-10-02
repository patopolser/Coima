import { getApiLanguage } from '../i18n'

const API_BASE = '/api'

function apiHeaders(extra = {}) {
  return {
    'Content-Type': 'application/json',
    'Accept-Language': getApiLanguage(),
    ...extra,
  }
}

async function request(path, options = {}) {
  const url = `${API_BASE}${path}`
  const res = await fetch(url, {
    headers: apiHeaders(options.headers),
    ...options,
  })
  if (!res.ok) {
    const body = await res.text()
    let detail = body
    try { detail = JSON.parse(body)?.detail ?? body } catch { /* plain-text body */ }
    // status lets pages tell "not found" (404) apart from network/server errors.
    const err = new Error(`${res.status}: ${typeof detail === 'string' ? detail : body}`)
    err.status = res.status
    err.detail = typeof detail === 'string' ? detail : ''
    throw err
  }
  return res.json()
}

// ── Dashboard ──────────────────────────────────────────────
export const fetchDashboardStats = () => request('/dashboard/stats')

// ── Detection ──────────────────────────────────────────────
export const fetchDetectionLatest = () => request('/detection/latest')
export const runDetection = (force = false, dateFrom = '', dateTo = '') => {
  const q = new URLSearchParams({ force: String(force) })
  if (dateFrom) q.set('date_from', dateFrom)
  if (dateTo) q.set('date_to', dateTo)
  return request(`/detection/run?${q}`, { method: 'POST' })
}

// ── Risk Scores ────────────────────────────────────────────
export const fetchRiskScores = (params = {}) => {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') q.set(k, v)
  }
  return request(`/risk-scores?${q}`)
}
export const fetchAllFlags = () => request('/risk-scores/flags')

// ── Checks ─────────────────────────────────────────────────
export const fetchChecks = () => request('/checks')
export const fetchCheck = (key, params = {}) => {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') q.set(k, v)
  }
  return request(`/checks/${key}?${q}`)
}

// ── Companies ──────────────────────────────────────────────
export const fetchCompany = (cuit) => request(`/companies/${cuit}`)

// ── Units ──────────────────────────────────────────────────
export const fetchUnits = (params = {}) => {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') q.set(k, v)
  }
  return request(`/units?${q}`)
}
// Encode each path segment but keep real slashes, so unit codes like "424/0"
// reach the backend's {code:path} route intact.
const encodePath = (s) => String(s).split('/').map(encodeURIComponent).join('/')
export const fetchUnit = (code) => request(`/units/${encodePath(code)}`)

// ── Authorizers ────────────────────────────────────────────
export const fetchAuthorizers = (params = {}) => {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') q.set(k, v)
  }
  return request(`/authorizers?${q}`)
}
export const fetchAuthorizer = (name) => request(`/authorizers/${encodeURIComponent(name)}`)

// ── Graph ──────────────────────────────────────────────────
function graphQuery(opts = {}) {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(opts)) {
    if (v !== undefined && v !== null && v !== '') q.set(k, v)
  }
  const qs = q.toString()
  return qs ? `?${qs}` : ''
}
export const fetchGraphCompany = (cuit, opts = {}) =>
  request(`/graph/company/${encodeURIComponent(cuit)}${graphQuery(opts)}`)
// Keep real slashes in unit codes (e.g. "424/0") so they reach the {code:path} route.
export const fetchGraphUnit = (code, opts = {}) =>
  request(`/graph/unit/${encodePath(code)}${graphQuery(opts)}`)
export const fetchGraphAuthorizer = (name, opts = {}) =>
  request(`/graph/authorizer/${encodeURIComponent(name)}${graphQuery(opts)}`)

// ── Config ─────────────────────────────────────────────────
export const fetchConfig = () => request('/config')
export const updateConfig = (body) =>
  request('/config', { method: 'PUT', body: JSON.stringify(body) })

// ── Scraper ────────────────────────────────────────────────
export const fetchScraperStatus = () => request('/scraper/status')
export const startScraper = (body = {}) =>
  request('/scraper/start', { method: 'POST', body: JSON.stringify(body) })
export const stopScraper = () => request('/scraper/stop', { method: 'POST' })
export const rescrapeOpenProcesses = (months) =>
  request('/scraper/rescrape-open', {
    method: 'POST',
    body: JSON.stringify(months ? { months } : {}),
  })
export const refreshScraperIndicators = () =>
  request('/scraper/refresh-indicators', { method: 'POST' })
