import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  fetchGraphCompany, fetchGraphUnit, fetchGraphAuthorizer,
  fetchUnits, fetchAuthorizers,
} from '../api/client'
import cytoscape from 'cytoscape'
import fcose from 'cytoscape-fcose'
import { useTranslation } from 'react-i18next'
import ProviderSearch from '../components/ProviderSearch'
import { useToast } from '../components/ui/Toast'
import { Reveal } from '../motion'
import { IconClose, IconExternal, IconArrowRight } from '../components/icons'
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

// Node palette for a light canvas: mid-saturation fills with a darker rim so
// shapes read on white; hue still separates entity types.
const NODE_COLORS = {
  Provider: { bg: '#2b7bb0', border: '#075f87' },
  Process: { bg: '#8fc3e0', border: '#4f93ba' },
  ContractualDocument: { bg: '#7cc3a0', border: '#3f8f69' },
  Email: { bg: '#f0a868', border: '#c47a35' },
  Phone: { bg: '#79c9c0', border: '#3b9a90' },
  Address: { bg: '#e99aa6', border: '#c2606f' },
  ContractingUnit: { bg: '#8a9bb0', border: '#55677d' },
  Authorizer: { bg: '#d9b45c', border: '#9a752f' },
  Bid: { bg: '#b49be0', border: '#7d63b4' },
  Cluster: { bg: '#e1f0f8', border: '#075f87' },
}
const DEFAULT_COLOR = { bg: '#b8c6d1', border: '#7f93a3' }

// Cluster is an internal UI artifact, not a data entity — keep it out of the legend.
const LEGEND = Object.entries(NODE_COLORS)
  .filter(([label]) => label !== 'Cluster')
  .map(([label, { bg }]) => ({ label, bg }))

// Edge colors by semantic kind set on the backend (plus the synthetic CLUSTER edge).
const EDGE_COLORS = {
  WON: '#2f8f5b',
  BID: '#9b86cf',
  CONTACT: '#9fb2c1',
  MANAGED: '#8a9bb0',
  AUTHORIZED: '#b8923f',
  CLUSTER: '#075f87',
}

const ENTITY_TYPES = ['provider', 'unit', 'authorizer']

export default function GraphExplorer() {
  const { t } = useTranslation()
  const toast = useToast()
  const [params] = useSearchParams()
  const cyRef = useRef(null)
  const containerRef = useRef(null)
  const navigate = useNavigate()
  const [count, setCount] = useState(0)
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
            color: '#102d3d',
            'font-size': '11px',
            'font-family': 'Inter, sans-serif',
            'text-background-color': '#ffffff',
            'text-background-opacity': 0.85,
            'text-background-padding': 2,
            'text-background-shape': 'roundrectangle',
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
          style: { shape: 'hexagon', width: 32, height: 30 },
        },
        {
          selector: 'node[group = "Cluster"]',
          style: {
            shape: 'round-rectangle', width: 56, height: 34,
            'font-size': '12px', 'font-weight': 700,
            'text-valign': 'center', 'text-margin-y': 0, color: '#075f87',
            'text-background-opacity': 0,
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
            color: '#355363',
            'font-family': 'Inter, sans-serif',
            'min-zoomed-font-size': 9,
            'text-rotation': 'autorotate',
            'text-background-color': '#ffffff',
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
          style: { width: 2.5, color: '#2f8f5b' },
        },
        {
          selector: 'edge[kind = "CLUSTER"]',
          style: { width: 2, 'line-style': 'dashed', 'target-arrow-shape': 'none' },
        },
        {
          selector: ':selected',
          style: {
            'border-color': '#102d3d',
            'border-width': 3,
            'overlay-color': '#075f87',
            'overlay-opacity': 0.08,
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
      setCount(loaded.current.size)
      mergeGraph(data)
      if (type === 'provider' && opts.won_only) await fetchNeighborProviders(opts)
      refresh()
    } catch (err) {
      toast(err.detail || err.message)
    } finally { setLoading(false) }
  }, [opts, fetchEntity, mergeGraph, refresh, fetchNeighborProviders, toast])

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
      toast(err.detail || err.message)
    } finally { setLoading(false) }
  }, [fetchEntity, mergeGraph, refresh, fetchNeighborProviders, toast])

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
    setCount(0)
  }, [])

  // Profiles link here with ?type=provider|unit|authorizer&id=... to open an
  // entity's network directly.
  const autoLoaded = useRef(false)
  useEffect(() => {
    const type = params.get('type')
    const id = params.get('id')
    if (autoLoaded.current || !id || !ENTITY_TYPES.includes(type)) return
    autoLoaded.current = true
    setEntityType(type)
    addEntity(type, id)
  }, [params, addEntity])

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

  // Node properties worth showing in the detail panel, with readable keys.
  const HIDDEN_PROPS = ['bg', 'borderColor', 'group', 'label', 'lineColor', 'source_url', 'members', 'provider', 'anchor']
  const humanize = k => k.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase())
  const nodeName = group => t(`graph.node.${group}`, { defaultValue: group })

  return (
    <Reveal>
      <div className="page-head">
        <h1 className="page-title">{t('graph.title')}</h1>
      </div>

      <section className="card toolbar" data-reveal="1" style={{ marginBottom: 12 }}>
        <div className="segmented" role="group" aria-label={t('graph.entityType')}>
          {ENTITY_TYPES.map(type => (
            <button key={type} type="button" aria-pressed={entityType === type} onClick={() => setEntityType(type)}>
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
          style={{ flex: '1 1 240px', maxWidth: 380 }}
        />
        {count > 0 && <button type="button" className="btn btn-ghost btn-sm" onClick={clearAll}>{t('common.clear')}</button>}

        <span className="toolbar-sep" />
        {togglePill('won_only', t('graph.wonOnly'))}
        {togglePill('show_earnings', t('graph.showEarnings'))}
        {togglePill('show_contacts', t('graph.showContacts'))}
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

        <span className="toolbar-sep" />
        <label className="field">
          {t('graph.dateFrom')}
          <input type="date" className="input input-sm" value={opts.date_from} onChange={e => setOpt('date_from', e.target.value)} />
        </label>
        <label className="field">
          {t('graph.dateTo')}
          <input type="date" className="input input-sm" value={opts.date_to} onChange={e => setOpt('date_to', e.target.value)} />
        </label>
      </section>

      <section className="card graph-canvas" data-reveal="2">
        <div ref={containerRef} className="graph-cy" />

        {count === 0 && !loading && (
          <div className="graph-empty">
            <p className="muted">{t('graph.empty')}</p>
          </div>
        )}

        {/* Node detail: opaque panel, never blur over a moving canvas. */}
        {selectedNode && (
          <div className="graph-panel" role="dialog" aria-label={selectedNode.label}>
            <div className="row" style={{ gap: 8 }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: NODE_COLORS[selectedNode.group]?.bg || DEFAULT_COLOR.bg }} />
              <span className="label">{nodeName(selectedNode.group)}</span>
              <span className="spacer" />
              <button type="button" className="btn btn-ghost btn-icon btn-sm" onClick={() => setSelectedNode(null)} aria-label={t('common.close')}>
                <IconClose size={14} />
              </button>
            </div>
            <div style={{ fontWeight: 600, marginTop: 8, overflowWrap: 'anywhere' }}>{selectedNode.label}</div>
            <dl>
              {Object.entries(selectedNode.properties)
                .filter(([k]) => !HIDDEN_PROPS.includes(k))
                .slice(0, 8)
                .map(([k, v]) => (
                  <div key={k} style={{ display: 'contents' }}>
                    <dt>{humanize(k)}</dt>
                    <dd title={String(v ?? '—')}>{String(v ?? '—')}</dd>
                  </div>
                ))}
            </dl>
            {selectedNode.cuit && (
              <button type="button" className="btn btn-primary btn-sm btn-block" onClick={() => navigate(`/companies/${selectedNode.cuit}`)}>
                {t('graph.viewCompany')} <IconArrowRight />
              </button>
            )}
            {selectedNode.group === 'ContractingUnit' && selectedNode.code && (
              <button type="button" className="btn btn-primary btn-sm btn-block" onClick={() => navigate(`/units/${encodeId(selectedNode.code)}`)}>
                {t('graph.viewUnit')} <IconArrowRight />
              </button>
            )}
            {selectedNode.group === 'Authorizer' && selectedNode.name && (
              <button type="button" className="btn btn-primary btn-sm btn-block" onClick={() => navigate(`/authorizers/${encodeId(selectedNode.name)}`)}>
                {t('graph.viewAuthorizer')} <IconArrowRight />
              </button>
            )}
            {selectedNode.group === 'Process' && selectedNode.source_url && (
              <a className="btn btn-secondary btn-sm btn-block" href={selectedNode.source_url} target="_blank" rel="noopener noreferrer">
                {t('graph.viewProcess')} <IconExternal className="" />
              </a>
            )}
          </div>
        )}

        {loading && <div className="graph-loading glass glass-strong" role="status">{t('common.loading')}</div>}

        <div className="graph-legend" aria-label={t('graph.legend')}>
          {LEGEND.map(({ label, bg }) => (
            <span key={label}><i style={{ background: bg }} />{nodeName(label)}</span>
          ))}
        </div>
      </section>
    </Reveal>
  )
}
