import { useState, useEffect, useRef, useId } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { fetchRiskScores } from '../api/client'
import { usePresence } from '../motion'
import { IconSearch } from './icons'

// Default behaviour: search providers by company name or CUIT (backed by the
// risk-scores endpoint, which matches both) and emit { cuit, company }.
const PROVIDER_SOURCE = {
  queryKey: 'provider',
  fetchResults: (search) => fetchRiskScores({ search, per_page: 8 }).then(d => d?.items || []),
  getKey: (item) => item.cuit,
  getPrimary: (item) => item.company || '—',
  getSecondary: (item) => item.cuit,
  toSelection: (item) => ({ cuit: item.cuit, company: item.company || '' }),
}

// Autocomplete with keyboard navigation. By default it searches providers, but
// it is fully parametrizable via `source` so the same dropdown/keyboard logic
// can drive unit and authorizer search (see GraphExplorer). With allowRaw,
// pressing Enter on free text that matches no suggestion submits it verbatim.
export default function ProviderSearch({
  onSelect,
  placeholder,
  style,
  allowRaw = false,
  autoFocus = false,
  source = PROVIDER_SOURCE,
}) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [open, setOpen] = useState(false)
  const [highlight, setHighlight] = useState(0)
  const boxRef = useRef(null)

  useEffect(() => {
    const id = setTimeout(() => setDebounced(query.trim()), 250)
    return () => clearTimeout(id)
  }, [query])

  const { data } = useQuery({
    queryKey: ['entity-search', source.queryKey, debounced],
    queryFn: () => source.fetchResults(debounced),
    enabled: debounced.length >= 2,
    placeholderData: keepPreviousData,
  })
  const results = debounced.length >= 2 ? (data || []) : []

  // Close the dropdown on outside click.
  useEffect(() => {
    const handler = e => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const reset = () => { setQuery(''); setDebounced(''); setOpen(false); setHighlight(0) }

  const choose = item => { onSelect(source.toSelection(item)); reset() }

  const onKeyDown = e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setHighlight(h => Math.min(h + 1, results.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHighlight(h => Math.max(h - 1, 0)) }
    else if (e.key === 'Enter') {
      e.preventDefault()
      if (open && results[highlight]) choose(results[highlight])
      else if (allowRaw && query.trim()) { onSelect({ cuit: query.trim(), company: '' }); reset() }
    } else if (e.key === 'Escape') { setOpen(false) }
  }

  const showList = open && results.length > 0
  const { mounted, ref: listRef } = usePresence(showList)
  const listId = useId()

  return (
    <div ref={boxRef} className="ac search-field" style={style}>
      <IconSearch className="search-field-icon" />
      <input
        className="input"
        value={query}
        autoFocus={autoFocus}
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-label={placeholder ?? t('common.searchProvider')}
        onChange={e => { setQuery(e.target.value); setOpen(true); setHighlight(0) }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        placeholder={placeholder ?? t('common.searchProvider')}
      />
      {mounted && (
        <div ref={listRef} id={listId} role="listbox" className="ac-list glass glass-strong">
          {results.map((item, i) => (
            <div
              key={source.getKey(item)}
              role="option"
              aria-selected={i === highlight}
              className="ac-item"
              onMouseDown={e => { e.preventDefault(); choose(item) }}
              onMouseEnter={() => setHighlight(i)}
            >
              <span className="ac-primary truncate">{source.getPrimary(item)}</span>
              {source.getSecondary(item) && <span className="ac-secondary">{source.getSecondary(item)}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
