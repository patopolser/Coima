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
    throw new Error(`${res.status}: ${body}`)
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

// ── Investigations ─────────────────────────────────────────
export const fetchInvestigations = (params = {}) => {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') q.set(k, v)
  }
  return request(`/investigations?${q}`)
}
export const fetchInvestigation = (id) => request(`/investigations/${id}`)
export const fetchInvestigationPrompt = (id, model) => request(`/investigations/${id}/prompt?model=${model}`)
export const createInvestigation = (body) =>
  request('/investigations', { method: 'POST', body: JSON.stringify(body) })
export const deleteInvestigation = (id) =>
  request(`/investigations/${id}`, { method: 'DELETE' })
export const updateInvestigationStatus = (id, status) =>
  request(`/investigations/${id}/status`, { method: 'PUT', body: JSON.stringify({ status }) })
export const addSubject = (id, subject) =>
  request(`/investigations/${id}/subjects`, { method: 'POST', body: JSON.stringify(subject) })
export const addNote = (id, text) =>
  request(`/investigations/${id}/notes`, { method: 'POST', body: JSON.stringify({ text }) })

// ── SSE helpers (chat + reports) ───────────────────────────
export async function* streamChat(investigationId, message, model = 'claude') {
  const res = await fetch(`${API_BASE}/investigations/${investigationId}/chat`, {
    method: 'POST',
    headers: apiHeaders(),
    body: JSON.stringify({ message, model }),
  })
  yield* parseSSE(res)
}

export async function* streamReport(investigationId, type, model = 'claude') {
  const res = await fetch(`${API_BASE}/investigations/${investigationId}/reports`, {
    method: 'POST',
    headers: apiHeaders(),
    body: JSON.stringify({ type, model }),
  })
  yield* parseSSE(res)
}

async function* parseSSE(response) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop()
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try { yield JSON.parse(line.slice(6)) } catch {}
      }
    }
  }
}

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
