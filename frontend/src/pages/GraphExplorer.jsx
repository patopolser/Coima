import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  fetchGraphCompany, fetchGraphUnit, fetchGraphAuthorizer,
  fetchUnits, fetchAuthorizers,
} from '../api/client'
import cytoscape from 'cytoscape'
import fcose from 'cytoscape-fcose'
import { useTranslation } from 'react-i18next'
import ProviderSearch from '../components/ProviderSearch'
import { encodeId } from '../utils/ids'

cytoscape.use(fcose)

// fcose layout config. Tuned to fan out the many Process nodes that hang off a
// single provider instead of piling them on top of each other: stronger
// repulsion, longer ideal edges, generous node separation and label-aware
// sizing so labels don't overlap. packComponents/tile keep disconnected
// sub-graphs from drifting apart. randomize:false keeps already-placed nodes
// stable when new entities are added incrementally.
const LAYOUT = {
  name: 'fcose',
  quality: 'default',
  animate: false,
  randomize: false,
  nodeDimensionsIncludeLabels: true,
  nodeRepulsion: 18000,
  idealEdgeLength: 95,
  edgeElasticity: 0.45,
  nodeSeparation: 110,
  gravity: 0.3,
  gravityRange: 3.8,
  packComponents: true,
  tile: true,
  numIter: 2500,
}

// A provider with more than this many degree-1 processes gets them collapsed
// into a single expandable "N processes" cluster node.
const CLUSTER_THRESHOLD = 12

const NODE_COLORS = {
  Provider: { bg: '#8b5cf6', border: '#7c3aed' },
  Process: { bg: '#3b82f6', border: '#2563eb' },
  ContractualDocument: { bg: '#10b981', border: '#059669' },
  Email: { bg: '#f97316', border: '#ea580c' },
  Phone: { bg: '#14b8a6', border: '#0d9488' },
  Address: { bg: '#f43f5e', border: '#e11d48' },
  ContractingUnit: { bg: '#64748b', border: '#475569' },
  Authorizer: { bg: '#eab308', border: '#ca8a04' },
  Bid: { bg: '#a855f7', border: '#9333ea' },
  Cluster: { bg: '#4338ca', border: '#6366f1' },
}
const DEFAULT_COLOR = { bg: '#94a3b8', border: '#64748b' }

// Cluster is an internal UI artifact, not a data entity — keep it out of the legend.
const LEGEND = Object.entries(NODE_COLORS)
  .filter(([label]) => label !== 'Cluster')
  .map(([label, { bg }]) => ({ label, bg }))

// Edge colors by semantic kind set on the backend (plus the synthetic CLUSTER edge).
const EDGE_COLORS = {
  WON: '#10b981',
  BID: '#a855f7',
  CONTACT: '#334155',
  MANAGED: '#64748b',
  AUTHORIZED: '#eab308',
  CLUSTER: '#6366f1',
}

const ENTITY_TYPES = ['provider', 'unit', 'authorizer']

export default function GraphExplorer() {
  const { t } = useTranslation()
  const cyRef = useRef(null)
  const containerRef = useRef(null)
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [entityType, setEntityType] = useState('provider')
  const [filterShared, setFilterShared] = useState(false)
  const filterSharedRef = useRef(false)
  const [groupProcesses, setGroupProcesses] = useState(true)
  const groupProcessesRef = useRef(true)
  const [selectedNode, setSelectedNode] = useState(null)

  // Backend filter options. Re-applied to every loaded entity when changed.
  const [opts, setOpts] = useState({
    won_only: false,
    show_earnings: false,
    show_contacts: true,
    date_from: '',
    date_to: '',
  })
  // Entities currently on the canvas, keyed `${type}::${id}`, so filter changes
  // can re-fetch them and won_only neighbour expansion can skip already-loaded ones.
  const loaded = useRef(new Map())
  // Providers the user manually expanded, so re-grouping doesn't recollapse them.
  const expandedProviders = useRef(new Set())

  // Init cytoscape once
  useEffect(() => {
    if (!containerRef.current) return
    const cy = cytoscape({
      container: containerRef.current,
      style: [
        {
          selector: 'node',
          style: {
            label: 'data(label)',
            'background-color': 'data(bg)',
            'border-color': 'data(borderColor)',
            'border-width': 2,
            color: '#f0f2f7',
            'font-size': '11px',
            'font-family': 'Inter, sans-serif',
            'text-valign': 'bottom',
            'text-margin-y': 6,
            width: 28, height: 28,
            'text-max-width': 100,
            'text-wrap': 'ellipsis',
            'min-zoomed-font-size': 8,
          },
        },
        {
          selector: 'node[group = "Process"]',
          style: { shape: 'round-rectangle', width: 34, height: 24 },
        },
        {
          selector: 'node[group = "ContractingUnit"]',
          style: { shape: 'diamond', width: 34, height: 34 },
        },
        {
          selector: 'node[group = "Authorizer"]',
          style: { shape: 'star', width: 34, height: 34 },
        },
        {
          selector: 'node[group = "Cluster"]',
          style: {
            shape: 'round-rectangle', width: 56, height: 34,
            'font-size': '12px', 'font-weight': 700,
            'text-valign': 'center', 'text-margin-y': 0, color: '#e0e7ff',
          },
        },
        {
          selector: 'edge',
          style: {
            width: 1,
            'line-color': 'data(lineColor)',
            'target-arrow-color': 'data(lineColor)',
            'target-arrow-shape': 'triangle',
            'arrow-scale': 0.6,
            label: 'data(label)',
            'font-size': '10px',
            'font-weight': 600,
            color: '#e2e8f0',
            'font-family': 'Inter, sans-serif',
            'min-zoomed-font-size': 9,
            'text-rotation': 'autorotate',
            'text-background-color': '#0a0e1f',
            'text-background-opacity': 0.9,
            'text-background-padding': 3,
            'text-background-shape': 'roundrectangle',
            'text-border-color': 'data(lineColor)',
            'text-border-width': 1,
            'text-border-opacity': 0.5,
            'curve-style': 'bezier',
          },
        },
        {
          selector: 'edge[kind = "WON"]',
          style: { width: 2.5, color: '#34d399' },
        },
        {
          selector: 'edge[kind = "CLUSTER"]',
          style: { width: 2, 'line-style': 'dashed', 'target-arrow-shape': 'none' },
        },
        {
          selector: ':selected',
          style: {
            'border-color': '#6366f1',
            'border-width': 3,
            'background-color': '#818cf8',
          },
        },
      ],
      layout: LAYOUT,
      minZoom: 0.2, maxZoom: 5,
      textureOnViewport: true,
      hideEdgesOnViewport: true,
      pixelRatio: 1,
    })
    cyRef.current = cy
    return () => cy.destroy()
  }, [])

  // Merge a fetched graph into the canvas. Does not clear existing elements.
  const mergeGraph = useCallback((data) => {
    const cy = cyRef.current
    if (!cy) return
    // Collect new elements and add them in one batched call. Per-element cy.add()
    // forces a recalc each time; a single add of the whole array is far cheaper.
    const toAdd = []
    const seen = new Set()
    data.nodes.forEach(n => {
      if (!seen.has(n.id) && cy.getElementById(n.id).empty()) {
        seen.add(n.id)
        const colors = NODE_COLORS[n.group] || DEFAULT_COLOR
        toAdd.push({ group: 'nodes', data: { ...n, bg: colors.bg, borderColor: colors.border } })
      }
    })
    const has = (id) => seen.has(id) || cy.getElementById(id).nonempty()
    data.edges.forEach(e => {
      const source = e.source ?? e.from
      const target = e.target ?? e.to
      if (!seen.has(e.id) && cy.getElementById(e.id).empty() && has(source) && has(target)) {
        seen.add(e.id)
        toAdd.push({
          group: 'edges',
          data: { ...e, source, target, lineColor: EDGE_COLORS[e.kind] || EDGE_COLORS.CONTACT },
        })
      }
    })
    if (toAdd.length) cy.add(toAdd)
  }, [])

  // Lay out only what's visible so collapsed cluster members (display:none)
  // don't reserve empty space in the spread.
  const runLayout = useCallback(() => {
    cyRef.current?.elements(':visible').layout(LAYOUT).run()
  }, [])

  // Rebuild process clusters from scratch. For each provider, the degree-1
  // processes wired to it (their only node neighbour is that provider) are
  // collapsed into one "N processes" node when they exceed the threshold,
  // unless the user has expanded that provider. Processes that also touch a
  // unit/authorizer/other provider are never clustered (they carry structure).
  const applyGrouping = useCallback(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.remove('[group = "Cluster"]')
    if (!groupProcessesRef.current) return
    const toAdd = []
    cy.nodes('[group = "Provider"]').forEach(prov => {
      if (expandedProviders.current.has(prov.id())) return
      const procs = prov.connectedEdges()
        .filter(e => e.data('kind') === 'WON' || e.data('kind') === 'BID')
        .connectedNodes()
        .filter(n => n.data('group') === 'Process'
          && n.neighborhood('node').filter(x => x.data('group') !== 'Cluster').length === 1)
      if (procs.length <= CLUSTER_THRESHOLD) return
      const clusterId = `cluster-${prov.id()}`
      const colors = NODE_COLORS.Cluster
      toAdd.push({
        group: 'nodes',
        data: {
          id: clusterId, group: 'Cluster', provider: prov.id(),
          label: t('graph.processCluster', { count: procs.length }),
          members: procs.map(n => n.id()),
          bg: colors.bg, borderColor: colors.border,
        },
      })
      toAdd.push({
        group: 'edges',
        data: {
          id: `clusteredge-${prov.id()}`, source: prov.id(), target: clusterId,
          kind: 'CLUSTER', label: '', lineColor: EDGE_COLORS.CLUSTER,
        },
      })
    })
    if (toAdd.length) cy.add(toAdd)
  }, [t])

  // Flag the nodes that correspond to entities the user explicitly loaded
  // (provider / unit / authorizer). The "shared only" filter uses these anchors
  // to reduce the canvas to the intersection between loaded entities.
  const markAnchors = useCallback(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.nodes().removeData('anchor')
    loaded.current.forEach(({ type, id }) => {
      const match =
        type === 'unit'
          ? cy.nodes().filter(n => n.data('group') === 'ContractingUnit' && n.data('code') === id)
          : type === 'authorizer'
            ? cy.nodes().filter(n => n.data('group') === 'Authorizer' && n.data('name') === id)
            : cy.nodes().filter(n => n.data('group') === 'Provider' && n.data('cuit') === id)
      match.data('anchor', true)
    })
  }, [])

  // Resolve node visibility. Cluster members are always hidden. With "shared
  // only" on, the canvas is cut down to the intersection of the loaded anchors:
  // anchors always stay; a Process is kept only if it bridges 2+ anchors (e.g.
  // the loaded unit AND a loaded provider) or 2+ providers; a contact is kept if
  // it links 2+ providers; a non-anchor provider is kept only if it touches one
  // of those shared nodes; clusters (an anchor's own degree-1 processes) are
  // hidden. Edges follow their endpoints automatically.
  const applyVisibility = useCallback(() => {
    const cy = cyRef.current
    if (!cy) return
    const shared = filterSharedRef.current
    const clustered = new Set()
    cy.nodes('[group = "Cluster"]').forEach(cl => {
      (cl.data('members') || []).forEach(id => clustered.add(id))
    })
    if (!shared) {
      cy.batch(() => cy.nodes().forEach(n =>
        n.style('display', clustered.has(n.id()) ? 'none' : 'element')))
      return
    }
    const CONTACTS = ['Email', 'Phone', 'Address']
    const sharedAux = new Set()
    cy.nodes().forEach(n => {
      const g = n.data('group')
      const nb = n.neighborhood('node')
      if (g === 'Process') {
        const anchors = nb.filter(x => x.data('anchor')).length
        const provs = nb.filter(x => x.data('group') === 'Provider').length
        if (anchors >= 2 || provs >= 2) sharedAux.add(n.id())
      } else if (CONTACTS.includes(g)) {
        if (nb.filter(x => x.data('group') === 'Provider').length >= 2) sharedAux.add(n.id())
      }
    })
    cy.batch(() => {
      cy.nodes().forEach(node => {
        if (clustered.has(node.id())) { node.style('display', 'none'); return }
        const g = node.data('group')
        if (node.data('anchor')) { node.style('display', 'element'); return }
        if (g === 'Cluster') { node.style('display', 'none'); return }
        if (g === 'Provider') {
          const touchesShared = node.neighborhood('node').some(x => sharedAux.has(x.id()))
          node.style('display', touchesShared ? 'element' : 'none'); return
        }
        if (g === 'Process' || CONTACTS.includes(g)) {
          node.style('display', sharedAux.has(node.id()) ? 'element' : 'none'); return
        }
        // Other non-anchor entities: keep only if they bridge 2+ anchors.
        const anchors = node.neighborhood('node').filter(x => x.data('anchor')).length
        node.style('display', anchors >= 2 ? 'element' : 'none')
      })
    })
  }, [])

  const refresh = useCallback(() => {
    markAnchors()
    applyGrouping()
    applyVisibility()
    runLayout()
  }, [markAnchors, applyGrouping, applyVisibility, runLayout])

  // Query-param object for a provider fetch.
  const providerParams = useCallback((o) => ({
    won_only: o.won_only,
    // Bids are always requested; "Solo ganados" (won_only) is what hides them.
    show_bids: true,
    show_earnings: o.show_earnings,
    show_contacts: o.show_contacts,
    date_from: o.date_from || undefined,
    date_to: o.date_to || undefined,
  }), [])

  // Unit/authorizer endpoints only take earnings + date range.
  const simpleParams = useCallback((o) => ({
    show_earnings: o.show_earnings,
    date_from: o.date_from || undefined,
    date_to: o.date_to || undefined,
  }), [])

  const fetchEntity = useCallback((type, id, o) => {
    if (type === 'unit') return fetchGraphUnit(id, simpleParams(o))
    if (type === 'authorizer') return fetchGraphAuthorizer(id, simpleParams(o))
    return fetchGraphCompany(id, providerParams(o))
  }, [providerParams, simpleParams])

  // With "Solo ganados" on, pull the won processes of every Provider already on
  // the canvas that wasn't explicitly loaded (neighbours from the contact
  // network). Fetched with show_contacts=false so they only contribute their own
  // processes and don't expand the network further.
  const fetchNeighborProviders = useCallback(async (o) => {
    const cy = cyRef.current
    if (!cy) return
    const extra = [...new Set(
      cy.nodes()
        .filter(n => n.data('group') === 'Provider' && n.data('cuit')
          && !loaded.current.has(`provider::${n.data('cuit')}`))
        .map(n => n.data('cuit'))
    )]
    if (!extra.length) return
    const results = await Promise.all(
      extra.map(c => fetchGraphCompany(c, { ...providerParams(o), show_contacts: false }))
    )
    results.forEach(mergeGraph)
  }, [providerParams, mergeGraph])

  const addEntity = useCallback(async (type, idArg) => {
    const id = String(idArg ?? '').trim()
    if (!id || !cyRef.current) return
    setLoading(true)
    try {
      const data = await fetchEntity(type, id, opts)
      loaded.current.set(`${type}::${id}`, { type, id })
      mergeGraph(data)
      if (type === 'provider' && opts.won_only) await fetchNeighborProviders(opts)
      refresh()
    } catch (err) {
      alert(`Error: ${err.message}`)
    } finally { setLoading(false) }
  }, [opts, fetchEntity, mergeGraph, refresh, fetchNeighborProviders])

  // Re-fetch every loaded entity with the new filters, replacing the canvas.
  const reloadAll = useCallback(async (nextOpts) => {
    const cy = cyRef.current
    if (!cy || loaded.current.size === 0) return
    setLoading(true)
    try {
      const entries = [...loaded.current.values()]
      const results = await Promise.all(entries.map(e => fetchEntity(e.type, e.id, nextOpts)))
      cy.elements().remove()
      expandedProviders.current.clear()
      results.forEach(mergeGraph)
      if (nextOpts.won_only) await fetchNeighborProviders(nextOpts)
      refresh()
    } catch (err) {
      alert(`Error: ${err.message}`)
    } finally { setLoading(false) }
  }, [fetchEntity, mergeGraph, refresh, fetchNeighborProviders])

  const setOpt = useCallback((key, value) => {
    const next = { ...opts, [key]: value }
    setOpts(next)
    reloadAll(next)
  }, [opts, reloadAll])

  // Node tap: Cluster → expand; Process → open its source URL; others → select.
  const onNodeTap = useCallback((e) => {
    const node = e.target
    const data = node.data()
    if (data.group === 'Cluster') {
      if (data.provider) expandedProviders.current.add(data.provider)
      refresh()
      return
    }
    if (data.group === 'Process' && data.source_url) {
      window.open(data.source_url, '_blank', 'noopener,noreferrer')
      return
    }
    setSelectedNode({
      id: data.id,
      label: data.label,
      group: data.group,
      cuit: data.cuit || (data.group === 'Provider' ? data.id : null),
      code: data.code || null,
      name: data.name || null,
      source_url: data.source_url || null,
      properties: Object.fromEntries(
        Object.entries(data).filter(([k]) => !['bg', 'borderColor', 'id', 'lineColor', 'members'].includes(k))
      ),
    })
  }, [refresh])

  useEffect(() => {
    if (!cyRef.current) return
    const cy = cyRef.current
    const bgHandler = (e) => { if (e.target === cy) setSelectedNode(null) }
    cy.on('tap', 'node', onNodeTap)
    cy.on('tap', bgHandler)
    return () => {
      cy.off('tap', 'node', onNodeTap)
      cy.off('tap', bgHandler)
    }
  }, [onNodeTap])

  useEffect(() => {
    filterSharedRef.current = filterShared
    refresh()
  }, [filterShared, refresh])

  useEffect(() => {
    groupProcessesRef.current = groupProcesses
    refresh()
  }, [groupProcesses, refresh])

  const clearAll = useCallback(() => {
    cyRef.current?.elements().remove()
    loaded.current.clear()
    expandedProviders.current.clear()
    setSelectedNode(null)
  }, [])

  const togglePill = (key, label) => (
    <label className={`toggle-pill${opts[key] ? ' active' : ''}`}>
      <input
        type="checkbox"
        checked={opts[key]}
        onChange={e => setOpt(key, e.target.checked)}
      />
      <span className="dot" />
      {label}
    </label>
  )

  // Search source + placeholder for the currently selected entity type.
  const SEARCH = {
    provider: {
      placeholder: t('graph.searchPlaceholder'),
      allowRaw: true,
      source: undefined, // ProviderSearch default (risk-scores)
      pick: (sel) => addEntity('provider', sel.cuit),
    },
    unit: {
      placeholder: t('graph.searchUnit'),
      allowRaw: false,
      source: {
        queryKey: 'unit',
        fetchResults: (s) => fetchUnits({ search: s, per_page: 8 }).then(d => d?.items || []),
        getKey: (i) => i.code,
        getPrimary: (i) => i.name || '—',
        getSecondary: (i) => i.code,
        toSelection: (i) => ({ id: i.code }),
      },
      pick: (sel) => addEntity('unit', sel.id),
    },
    authorizer: {
      placeholder: t('graph.searchAuthorizer'),
      allowRaw: false,
      source: {
        queryKey: 'authorizer',
        fetchResults: (s) => fetchAuthorizers({ search: s, per_page: 8 }).then(d => d?.items || []),
        getKey: (i) => i.authorizer,
        getPrimary: (i) => i.authorizer,
        getSecondary: () => '',
        toSelection: (i) => ({ id: i.authorizer }),
      },
      pick: (sel) => addEntity('authorizer', sel.id),
    },
  }
  const search = SEARCH[entityType]

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">{t('graph.title')}</h1>
        <p className="page-subtitle">{t('graph.subtitle')}</p>
      </div>

      <div className="flex gap-3 mb-4 flex-wrap items-center">
        {/* Entity-type selector */}
        <div className="flex" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', padding: 2 }}>
          {ENTITY_TYPES.map(type => (
            <button
              key={type}
              className={`btn btn-sm ${entityType === type ? 'btn-primary' : 'btn-ghost'}`}
              style={{ borderRadius: 'var(--radius-sm)' }}
              onClick={() => setEntityType(type)}
            >
              {t(`graph.entity_${type}`)}
            </button>
          ))}
        </div>

        <ProviderSearch
          key={entityType}
          onSelect={search.pick}
          placeholder={search.placeholder}
          allowRaw={search.allowRaw}
          source={search.source}
          style={{ flex: 1, maxWidth: 360 }}
        />
        <button className="btn btn-danger btn-sm" onClick={clearAll}>{t('common.clear')}</button>
      </div>

      {/* Configuration panel */}
      <div className="card mb-4" style={{ padding: 16, display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
        {togglePill('won_only', t('graph.wonOnly'))}
        {togglePill('show_earnings', t('graph.showEarnings'))}
        {togglePill('show_contacts', t('graph.showContacts'))}

        <span style={{ width: 1, height: 24, background: 'var(--border)' }} />

        <div className="field-inline">
          <span>{t('graph.dateFrom')}</span>
          <input type="date" className="input"
            value={opts.date_from} onChange={e => setOpt('date_from', e.target.value)} />
        </div>
        <div className="field-inline">
          <span>{t('graph.dateTo')}</span>
          <input type="date" className="input"
            value={opts.date_to} onChange={e => setOpt('date_to', e.target.value)} />
        </div>

        <span style={{ width: 1, height: 24, background: 'var(--border)' }} />

        <label className={`toggle-pill${groupProcesses ? ' active' : ''}`}>
          <input type="checkbox" checked={groupProcesses} onChange={e => setGroupProcesses(e.target.checked)} />
          <span className="dot" />
          {t('graph.groupProcesses')}
        </label>

        <label className={`toggle-pill${filterShared ? ' active' : ''}`}>
          <input type="checkbox" checked={filterShared} onChange={e => setFilterShared(e.target.checked)} />
          <span className="dot" />
          {t('graph.sharedOnly')}
        </label>
      </div>

      <div className="card" style={{ position: 'relative', overflow: 'hidden' }}>
        <div ref={containerRef} style={{ width: '100%', height: 640, background: 'var(--bg-deep)' }} />

        {/* Legend */}
        <div style={{ position: 'absolute', bottom: 16, left: 16, display: 'flex', gap: 8, flexWrap: 'wrap', maxWidth: 'calc(100% - 32px)' }}>
          {LEGEND.map(({ label, bg }) => (
            <div key={label} style={{ padding: '4px 10px', borderRadius: 'var(--radius-full)', background: 'var(--bg-glass)', backdropFilter: 'blur(8px)', border: '1px solid var(--border)', fontSize: 11, fontWeight: 500, display: 'flex', alignItems: 'center', gap: 6, color: 'var(--text-secondary)' }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: bg }} />
              {label}
            </div>
          ))}
        </div>

        {/* Node detail panel */}
        {selectedNode && (
          <div style={{
            position: 'absolute', top: 12, right: 12, width: 240,
            background: 'var(--bg-glass)', backdropFilter: 'blur(16px)',
            border: '1px solid var(--border-hover)', borderRadius: 'var(--radius-lg)',
            padding: 16, zIndex: 10,
          }}>
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <span style={{ width: 10, height: 10, borderRadius: '50%', background: NODE_COLORS[selectedNode.group]?.bg || DEFAULT_COLOR.bg }} />
                <span className="text-xs font-semibold uppercase" style={{ color: 'var(--text-muted)' }}>{selectedNode.group}</span>
              </div>
              <button className="text-xs text-muted" onClick={() => setSelectedNode(null)}>✕</button>
            </div>
            <div className="font-semibold text-sm mb-3 truncate">{selectedNode.label}</div>
            <div className="flex flex-col gap-1 mb-3">
              {Object.entries(selectedNode.properties)
                .filter(([k]) => !['bg', 'borderColor', 'group', 'label', 'lineColor', 'source_url', 'members', 'provider'].includes(k))
                .slice(0, 8)
                .map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-2">
                    <span className="text-xs text-muted truncate">{k}</span>
                    <span className="text-xs text-secondary truncate" style={{ maxWidth: 120 }}>{String(v ?? '—')}</span>
                  </div>
                ))}
            </div>
            {selectedNode.cuit && (
              <button className="btn btn-primary btn-sm" style={{ width: '100%', justifyContent: 'center' }}
                onClick={() => navigate(`/companies/${selectedNode.cuit}`)}>
                {t('graph.viewCompany')}
              </button>
            )}
            {selectedNode.group === 'ContractingUnit' && selectedNode.code && (
              <button className="btn btn-primary btn-sm" style={{ width: '100%', justifyContent: 'center' }}
                onClick={() => navigate(`/units/${encodeId(selectedNode.code)}`)}>
                {t('graph.viewUnit')}
              </button>
            )}
            {selectedNode.group === 'Authorizer' && selectedNode.name && (
              <button className="btn btn-primary btn-sm" style={{ width: '100%', justifyContent: 'center' }}
                onClick={() => navigate(`/authorizers/${encodeURIComponent(selectedNode.name)}`)}>
                {t('graph.viewAuthorizer')}
              </button>
            )}
            {selectedNode.group === 'Process' && selectedNode.source_url && (
              <button className="btn btn-ghost btn-sm" style={{ width: '100%', justifyContent: 'center', marginTop: 8 }}
                onClick={() => window.open(selectedNode.source_url, '_blank', 'noopener,noreferrer')}>
                {t('graph.viewProcess')}
              </button>
            )}
          </div>
        )}

        {loading && (
          <div style={{ position: 'absolute', top: 16, left: '50%', transform: 'translateX(-50%)', padding: '6px 14px', background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', fontSize: 12, color: 'var(--text-secondary)' }}>
            {t('common.loading')}
          </div>
        )}
      </div>
    </>
  )
}
