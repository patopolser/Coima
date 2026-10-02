import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { getApiLanguage } from '../i18n'
import { IconContact, IconExternal } from '../components/icons'
import { encodeId } from './ids'
import { formatCompactMoney, formatFullMoney } from './money'

const formatLocale = () => (getApiLanguage() === 'es' ? 'es-AR' : 'en-US')

const isObject = value => value && typeof value === 'object' && !Array.isArray(value)

const inferType = (key, meta = {}) => {
  if (!key) return undefined
  if ((meta.cuit_columns || []).includes(key)) return 'Provider'
  if ((meta.unit_columns || []).includes(key)) return 'Unit'
  if (meta.url_columns && meta.url_columns[key]) return 'Process'
  return undefined
}

export function normalizeColumns(columns = [], meta = {}) {
  return (columns || []).map(col => {
    if (Array.isArray(col)) {
      const key = col[0]
      const label = col[1] ?? col[0]
      return { key, label, type: inferType(key, meta) || 'String' }
    }
    if (isObject(col)) {
      const key = col.key
      const label = col.label ?? key
      const inferred = inferType(key, meta)
      const resolvedType = col.type && col.type !== 'String' ? col.type : (inferred || col.type || 'String')
      return { ...col, key, label, type: resolvedType }
    }
    return null
  }).filter(Boolean)
}

const formatNumber = value => {
  if (typeof value === 'number') return value.toLocaleString(formatLocale())
  return value
}

// Compact money badge with the exact amount in the tooltip.
const MoneyCell = ({ amount, currency, pill = false }) => (
  <span
    className={pill ? 'cell-pill' : 'cell-badge money'}
    title={formatFullMoney(amount, currency, formatLocale())}
  >
    {formatCompactMoney(amount, currency, formatLocale())}
  </span>
)

const formatDate = value => {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(formatLocale())
}

const LIST_INITIAL = 3

function CollapsibleList({ items }) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)
  const visible = expanded ? items : items.slice(0, LIST_INITIAL)
  const hidden = items.length - LIST_INITIAL
  return (
    <div className="cell-list">
      {visible}
      {!expanded && hidden > 0 && (
        <button
          className="cell-show-more"
          onClick={e => { e.stopPropagation(); setExpanded(true) }}
        >
          {t('common.showMore', { count: hidden })}
        </button>
      )}
      {expanded && hidden > 0 && (
        <button
          className="cell-show-more"
          onClick={e => { e.stopPropagation(); setExpanded(false) }}
        >
          {t('common.showLess')}
        </button>
      )}
    </div>
  )
}

function ExternalLink({ href, children, className = '', style }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={`cell-link ${className}`.trim()}
      style={style}
    >
      {children}
      <IconExternal />
    </a>
  )
}

function renderContactPill(item, pillKey) {
  if (!isObject(item)) {
    return <span key={pillKey} className="cell-pill">{item}</span>
  }
  const contact = item.contact ?? item.value ?? ''
  return (
    <span key={pillKey} className="cell-pill" title={item.type ? String(item.type) : undefined}>
      <IconContact type={item.type} />
      <span>{contact}</span>
    </span>
  )
}

export function renderColumnCell(column, row, meta = {}, options = {}) {
  const key = column.key
  const value = row?.[key]
  const type = column.type || inferType(key, meta) || 'String'
  const nameKey = column.name_key
  const urlKey = column.url_key || (meta.url_columns ? meta.url_columns[key] : undefined)
  const currentCuit = options.cuit
  const linkStyle = { color: 'var(--accent)', fontWeight: 500 }

  if (value === null || value === undefined || value === '') {
    return <span>—</span>
  }

  switch (type) {
    case 'Process': {
      const url = urlKey ? row?.[urlKey] : undefined
      if (url) {
        return (
          <ExternalLink href={url} style={linkStyle}>
            {value}
          </ExternalLink>
        )
      }
      return <span>{value}</span>
    }
    case 'Provider': {
      const name = nameKey ? row?.[nameKey] : undefined
      const externalUrl = urlKey ? row?.[urlKey] : undefined
      const showLink = value && value !== currentCuit
      return (
        <span>
          {showLink ? (
            <Link to={`/companies/${value}`} className="cell-mono" style={linkStyle}>{value}</Link>
          ) : (
            <span className="cell-mono">{value}</span>
          )}
          {name ? <span className="cell-truncate" style={{ marginLeft: 6 }} title={String(name)}>{name}</span> : null}
          {externalUrl ? (
            <a
              href={externalUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="cell-link cell-link-icon-only"
              style={{ marginLeft: 6 }}
              title="External profile"
            >
              <IconExternal size={13} />
            </a>
          ) : null}
        </span>
      )
    }
    case 'Unit': {
      const name = nameKey ? row?.[nameKey] : undefined
      return (
        <span>
          <Link to={`/units/${encodeId(value)}`} className="cell-truncate" style={linkStyle} title={String(value)}>{value}</Link>
          {name ? <span className="cell-truncate" style={{ marginLeft: 6 }} title={String(name)}>{name}</span> : null}
        </span>
      )
    }
    case 'Authorizer': {
      return (
        <Link to={`/authorizers/${encodeId(value)}`} className="cell-truncate" style={linkStyle} title={String(value)}>{value}</Link>
      )
    }
    case 'Organization': {
      const name = nameKey ? row?.[nameKey] : undefined
      const text = name ? `${value} ${name}` : value
      return <span className="cell-truncate" title={String(text)}>{text}</span>
    }
    case 'Quantity':
      return <span>{formatNumber(value)}</span>
    case 'Percentage':
      return <span className="cell-badge percent">{value}%</span>
    case 'Money':
      return <MoneyCell amount={value} currency={column.currency_key ? row?.[column.currency_key] : undefined} />
    case 'Date':
      return <span>{formatDate(value)}</span>
    case 'Contact': {
      if (isObject(value)) return renderContactPill(value, key)
      return <span>{value}</span>
    }
    case 'ListProcess': {
      const list = Array.isArray(value) ? value : []
      const items = list.map((item, index) => {
        const label = item?.process_number ?? item?.process ?? ''
        const url = item?.comprar_url
        const content = url ? (
          <ExternalLink href={url}>{label}</ExternalLink>
        ) : (
          <span>{label}</span>
        )
        return <span key={`${key}-${index}`} className="cell-pill">{content}</span>
      })
      return <CollapsibleList items={items} />
    }
    case 'ListUnit': {
      const list = Array.isArray(value) ? value : []
      const items = list.map((item, index) => {
        const code = item?.code ?? item?.unit_code ?? ''
        const name = item?.name
        return (
          <span key={`${key}-${index}`} className="cell-pill">
            <Link to={`/units/${encodeId(code)}`} className="cell-truncate" style={linkStyle} title={String(code)}>{code}</Link>
            {name ? <span className="cell-truncate" title={String(name)}>{name}</span> : null}
          </span>
        )
      })
      return <CollapsibleList items={items} />
    }
    case 'ListOrganization': {
      const list = Array.isArray(value) ? value : []
      const items = list.map((item, index) => {
        const code = item?.saf_code ?? item?.org_saf_code ?? ''
        const name = item?.name
        return <span key={`${key}-${index}`} className="cell-pill">{name ? `${code} ${name}` : code}</span>
      })
      return <CollapsibleList items={items} />
    }
    case 'ListContact': {
      const list = Array.isArray(value) ? value : []
      const items = list.map((item, index) => {
        return renderContactPill(item, `${key}-${index}`)
      })
      return <CollapsibleList items={items} />
    }
    case 'ListMoney': {
      const list = Array.isArray(value) ? value : []
      const items = list.map((item, index) => (
        <MoneyCell key={`${key}-${index}`} amount={item?.amount} currency={item?.currency} pill />
      ))
      return <CollapsibleList items={items} />
    }
    case 'ListString': {
      const list = Array.isArray(value) ? value : [value]
      const items = list.map((item, index) => {
        if (isObject(item)) return <span key={`${key}-${index}`} className="cell-pill">{item.text}</span>
        return <span key={`${key}-${index}`} className="cell-pill">{item}</span>
      })
      return <CollapsibleList items={items} />
    }
    case 'String': {
      const text = String(value)
      return <span className="cell-truncate" title={text}>{text}</span>
    }
    default: {
      if (Array.isArray(value)) return <span>{value.join(', ')}</span>
      return <span>{value}</span>
    }
  }
}
