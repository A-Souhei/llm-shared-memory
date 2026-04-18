'use client'

import { useState, useEffect, useCallback, useRef } from 'react'

// ─── Types ─────────────────────────────────────────────────────────────────────

interface BiblionReady {
  type: 'ready'
  entry_count: number
  token_count: number
  embedding_model: string
  redis_url: string
  embedding_url: string
}
interface BiblionDisabled { type: 'disabled'; reason: string }
type BiblionStatus = BiblionReady | BiblionDisabled

interface IndexerStatus {
  status: 'ok' | 'disabled'
  reason?: string
  projects: string[]
}

interface StatusData {
  biblion: BiblionStatus
  indexer: IndexerStatus
}

interface NodeInfo {
  nodeID: string
  role: 'master' | 'friend'
  sessionID: string
  slug: string
  title: string
  directory: string
  nodeURL: string
  heartbeat: number
  status: 'active' | 'inactive' | 'stale'
  project_id: string
}

interface BridgeInfo {
  bridgeID: string
  masterID: string
  masterSlug: string
  nodes: NodeInfo[]
  limit: number
  createdAt: number
}

interface ProjectData {
  projectId: string
  biblionCount: number
  biblionByType: Record<string, number>
  chunkCount: number
  fileCount: number
}

interface BiblionResult {
  id: string
  type: string
  content: string
  tags: string[]
  quality: number
  used_count: number
  similarity: number
  score: number
  project_id: string
}

interface IndexerResult {
  file_path: string
  start_line: number
  text: string
  score: number
}

interface Toast { id: number; message: string; kind: 'success' | 'error' }
interface ConfirmState { message: string; onConfirm: () => Promise<void> }

const TYPE_COLORS: Record<string, string> = {
  structure:  'bg-blue-100 text-blue-800',
  pattern:    'bg-purple-100 text-purple-800',
  dependency: 'bg-orange-100 text-orange-800',
  api:        'bg-green-100 text-green-800',
  config:     'bg-yellow-100 text-yellow-800',
  workflow:   'bg-pink-100 text-pink-800',
}

// ─── Page ──────────────────────────────────────────────────────────────────────

export default function Home() {
  const [tab, setTab] = useState<'projects' | 'bridge' | 'search'>('projects')
  const [status, setStatus] = useState<StatusData | null>(null)
  const [projects, setProjects] = useState<ProjectData[]>([])
  const [bridges, setBridges] = useState<BridgeInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [confirm, setConfirm] = useState<ConfirmState | null>(null)
  const [toasts, setToasts] = useState<Toast[]>([])
  const toastId = useRef(0)

  const addToast = useCallback((message: string, kind: 'success' | 'error') => {
    const id = ++toastId.current
    setToasts(prev => [...prev, { id, message, kind }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4000)
  }, [])

  const fetchData = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true)
    try {
      const [sRes, pRes, bRes] = await Promise.all([
        fetch('/api/status'),
        fetch('/api/projects'),
        fetch('/api/bridge'),
      ])
      if (sRes.ok) setStatus(await sRes.json())
      if (pRes.ok) setProjects(await pRes.json())
      if (bRes.ok) setBridges(await bRes.json())
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const askConfirm = (message: string, action: () => Promise<void>) =>
    setConfirm({ message, onConfirm: action })

  const clearBiblion = async (projectId: string) => {
    const url = new URL('/api/biblion/clear', window.location.origin)
    url.searchParams.set('project_id', projectId)
    const res = await fetch(url.toString(), { method: 'DELETE' })
    const data = await res.json()
    if (res.ok) {
      addToast(`Deleted ${data.deleted} biblion entries`, 'success')
      fetchData(true)
    } else {
      addToast('Failed to clear biblion entries', 'error')
    }
  }

  const clearIndex = async (projectId: string) => {
    const res = await fetch('/api/indexer/clear', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: projectId }),
    })
    const data = await res.json()
    if (res.ok) {
      addToast(`Deleted ${data.deleted} index chunks`, 'success')
      fetchData(true)
    } else {
      addToast('Failed to clear index', 'error')
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-slate-900 text-white px-6 py-4 flex items-center justify-between shadow">
        <span className="text-base font-semibold tracking-tight">Biblion</span>
        <div className="flex gap-5 text-sm">
          <StatusPill label="Biblion" ok={status?.biblion.type === 'ready'} />
          <StatusPill label="Indexer" ok={status?.indexer.status === 'ok'} />
        </div>
      </header>

      {/* Sub-header: status details */}
      <div className="bg-slate-800 text-slate-400 px-6 py-2 text-xs flex gap-5 flex-wrap">
        {status?.biblion.type === 'ready' && (
          <>
            <span>{status.biblion.entry_count} entries</span>
            <span className="text-slate-500">·</span>
            <span>{status.biblion.embedding_model}</span>
            <span className="text-slate-500">·</span>
            <span>{status.biblion.redis_url}</span>
          </>
        )}
        {status?.biblion.type === 'disabled' && (
          <span className="text-red-400">Biblion disabled: {status.biblion.reason}</span>
        )}
        {status?.indexer.status === 'disabled' && (
          <span className="text-red-400">Indexer disabled: {status.indexer.reason}</span>
        )}
      </div>

      {/* Tabs */}
      <nav className="bg-white border-b px-6 flex">
        {(['projects', 'bridge', 'search'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-3 text-sm font-medium capitalize border-b-2 transition-colors flex items-center gap-1.5 ${
              tab === t
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-800'
            }`}
          >
            {t}
            {t === 'bridge' && bridges.length > 0 && (
              <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${tab === 'bridge' ? 'bg-blue-100 text-blue-600' : 'bg-gray-100 text-gray-500'}`}>
                {bridges.length}
              </span>
            )}
          </button>
        ))}
      </nav>

      {/* Content */}
      <main className="p-6 max-w-6xl mx-auto">
        {tab === 'projects' && (
          <ProjectsTab
            projects={projects}
            loading={loading}
            refreshing={refreshing}
            onRefresh={() => fetchData(true)}
            onClearBiblion={id =>
              askConfirm(
                `Clear all biblion entries for "${id || '(global)'}"?`,
                () => clearBiblion(id),
              )
            }
            onClearIndex={id =>
              askConfirm(
                `Clear code index for "${id || '(global)'}"?`,
                () => clearIndex(id),
              )
            }
          />
        )}
        {tab === 'bridge' && (
          <BridgeTab
            bridges={bridges}
            loading={loading}
            refreshing={refreshing}
            onRefresh={() => fetchData(true)}
          />
        )}
        {tab === 'search' && <SearchTab projects={projects} addToast={addToast} />}
      </main>

      {/* Confirm modal */}
      {confirm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-2xl max-w-sm w-full p-6">
            <p className="text-gray-800 text-sm mb-6 leading-relaxed">{confirm.message}</p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setConfirm(null)}
                className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 rounded"
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  const action = confirm.onConfirm
                  setConfirm(null)
                  await action()
                }}
                className="px-4 py-2 text-sm bg-red-600 text-white rounded hover:bg-red-700 font-medium"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toasts */}
      <div className="fixed bottom-4 right-4 flex flex-col gap-2 z-50">
        {toasts.map(t => (
          <div
            key={t.id}
            className={`px-4 py-3 rounded-lg shadow-lg text-sm text-white font-medium ${
              t.kind === 'success' ? 'bg-green-600' : 'bg-red-600'
            }`}
          >
            {t.message}
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── StatusPill ─────────────────────────────────────────────────────────────────

function StatusPill({ label, ok }: { label: string; ok: boolean | undefined }) {
  const color =
    ok === undefined ? 'bg-gray-500'
    : ok ? 'bg-green-400'
    : 'bg-red-400'
  return (
    <span className="flex items-center gap-1.5 text-slate-300">
      <span className={`w-2 h-2 rounded-full ${color}`} />
      {label}
    </span>
  )
}

// ─── ProjectsTab ────────────────────────────────────────────────────────────────

function ProjectsTab({
  projects,
  loading,
  refreshing,
  onRefresh,
  onClearBiblion,
  onClearIndex,
}: {
  projects: ProjectData[]
  loading: boolean
  refreshing: boolean
  onRefresh: () => void
  onClearBiblion: (id: string) => void
  onClearIndex: (id: string) => void
}) {
  const totalEntries = projects.reduce((s, p) => s + p.biblionCount, 0)
  const totalChunks  = projects.reduce((s, p) => s + p.chunkCount, 0)

  if (loading) {
    return (
      <div className="flex items-center justify-center h-40 text-gray-400 text-sm">
        Loading…
      </div>
    )
  }

  return (
    <div>
      {/* Summary row */}
      <div className="flex items-center justify-between mb-5">
        <div className="flex gap-6 text-sm text-gray-600">
          <span>
            <span className="font-semibold text-gray-800">{projects.length}</span> projects
          </span>
          <span>
            <span className="font-semibold text-gray-800">{totalEntries}</span> biblion entries
          </span>
          <span>
            <span className="font-semibold text-gray-800">{totalChunks}</span> index chunks
          </span>
        </div>
        <button
          onClick={onRefresh}
          disabled={refreshing}
          className="text-sm text-blue-600 hover:text-blue-800 disabled:opacity-40 font-medium"
        >
          {refreshing ? 'Refreshing…' : '↻ Refresh'}
        </button>
      </div>

      {projects.length === 0 ? (
        <div className="bg-white rounded-xl border p-10 text-center text-gray-400 text-sm">
          No projects found. Start by indexing a codebase or writing a biblion entry.
        </div>
      ) : (
        <div className="bg-white rounded-xl border overflow-hidden shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left px-5 py-3 font-medium text-gray-500 text-xs uppercase tracking-wider">Project</th>
                <th className="text-left px-5 py-3 font-medium text-gray-500 text-xs uppercase tracking-wider">Biblion entries</th>
                <th className="text-left px-5 py-3 font-medium text-gray-500 text-xs uppercase tracking-wider">Code index</th>
                <th className="text-right px-5 py-3 font-medium text-gray-500 text-xs uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {projects.map(p => (
                <tr key={p.projectId} className="hover:bg-gray-50/60 transition-colors">
                  <td className="px-5 py-4">
                    {p.projectId === '' ? (
                      <span className="italic text-gray-400 font-mono">(global)</span>
                    ) : (
                      <span className="font-mono text-gray-800">{p.projectId}</span>
                    )}
                  </td>

                  <td className="px-5 py-4">
                    {p.biblionCount === 0 ? (
                      <span className="text-gray-300">—</span>
                    ) : (
                      <div>
                        <div className="font-medium text-gray-800 mb-1.5">{p.biblionCount}</div>
                        <div className="flex flex-wrap gap-1">
                          {Object.entries(p.biblionByType).map(([type, count]) => (
                            <span
                              key={type}
                              className={`px-1.5 py-0.5 rounded text-xs font-medium ${TYPE_COLORS[type] ?? 'bg-gray-100 text-gray-600'}`}
                            >
                              {type} {count}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </td>

                  <td className="px-5 py-4">
                    {p.chunkCount === 0 ? (
                      <span className="text-gray-300">—</span>
                    ) : (
                      <div>
                        <div className="font-medium text-gray-800">{p.chunkCount} chunks</div>
                        <div className="text-xs text-gray-400 mt-0.5">{p.fileCount} files</div>
                      </div>
                    )}
                  </td>

                  <td className="px-5 py-4 text-right">
                    <div className="flex gap-2 justify-end">
                      <button
                        onClick={() => onClearBiblion(p.projectId)}
                        disabled={p.biblionCount === 0}
                        className="px-2.5 py-1 text-xs border border-red-200 text-red-600 rounded-md hover:bg-red-50 disabled:opacity-25 disabled:cursor-not-allowed transition-colors"
                      >
                        Clear biblion
                      </button>
                      <button
                        onClick={() => onClearIndex(p.projectId)}
                        disabled={p.chunkCount === 0}
                        className="px-2.5 py-1 text-xs border border-orange-200 text-orange-600 rounded-md hover:bg-orange-50 disabled:opacity-25 disabled:cursor-not-allowed transition-colors"
                      >
                        Clear index
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ─── SearchTab ──────────────────────────────────────────────────────────────────

function SearchTab({
  projects,
  addToast,
}: {
  projects: ProjectData[]
  addToast: (msg: string, kind: 'success' | 'error') => void
}) {
  const [mode, setMode] = useState<'biblion' | 'indexer'>('biblion')
  const [query, setQuery] = useState('')
  const [projectId, setProjectId] = useState('')
  const [limit, setLimit] = useState(10)
  const [biblionResults, setBiblionResults] = useState<BiblionResult[]>([])
  const [indexerResults, setIndexerResults] = useState<IndexerResult[]>([])
  const [searching, setSearching] = useState(false)

  const indexerProjects = projects.filter(p => p.chunkCount > 0)
  const biblionProjects = projects.filter(p => p.biblionCount > 0)
  const projectOptions = mode === 'biblion' ? biblionProjects : indexerProjects

  const switchMode = (m: 'biblion' | 'indexer') => {
    setMode(m)
    setBiblionResults([])
    setIndexerResults([])
    // code index requires a project — auto-select first available
    if (m === 'indexer') {
      const first = projects.find(p => p.chunkCount > 0)
      setProjectId(first?.projectId ?? '')
    } else {
      setProjectId('')
    }
  }

  const canSearch = query.trim() !== '' && (mode === 'biblion' || projectId !== '')

  const search = async () => {
    if (!canSearch) return
    setSearching(true)
    setBiblionResults([])
    setIndexerResults([])
    try {
      if (mode === 'biblion') {
        const res = await fetch('/api/search/biblion', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query, project_id: projectId, limit }),
        })
        if (res.ok) setBiblionResults(await res.json())
        else addToast('Biblion search failed', 'error')
      } else {
        const res = await fetch('/api/search/indexer', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query, project_id: projectId, top_k: limit }),
        })
        if (res.ok) {
          const data = await res.json()
          setIndexerResults(data.results ?? [])
        } else {
          addToast('Index search failed', 'error')
        }
      }
    } finally {
      setSearching(false)
    }
  }

  const resultCount = mode === 'biblion' ? biblionResults.length : indexerResults.length

  return (
    <div className="max-w-3xl">
      {/* Mode toggle */}
      <div className="flex bg-gray-100 rounded-lg p-1 w-fit mb-6">
        {(['biblion', 'indexer'] as const).map(m => (
          <button
            key={m}
            onClick={() => switchMode(m)}
            className={`px-4 py-1.5 text-sm rounded-md font-medium transition-all ${
              mode === m
                ? 'bg-white shadow text-gray-900'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {m === 'biblion' ? 'Knowledge base' : 'Code index'}
          </button>
        ))}
      </div>

      {/* Form */}
      <div className="bg-white rounded-xl border shadow-sm p-4 mb-4">
        <div className="flex gap-2 mb-3">
          <input
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && search()}
            placeholder={mode === 'biblion' ? 'Search knowledge base…' : 'Search code index…'}
            className="flex-1 px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-gray-50"
          />
          <button
            onClick={search}
            disabled={searching || !canSearch}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50 font-medium transition-colors"
          >
            {searching ? 'Searching…' : 'Search'}
          </button>
        </div>
        <div className="flex gap-4 flex-wrap items-center">
          <label className="flex items-center gap-2 text-sm text-gray-500">
            Project
            <select
              value={projectId}
              onChange={e => setProjectId(e.target.value)}
              className="border rounded-md px-2 py-1 text-sm focus:outline-none text-gray-700 bg-white"
            >
              {mode === 'biblion' && <option value="">All</option>}
              {mode === 'indexer' && projectOptions.length === 0 && (
                <option value="" disabled>No indexed projects</option>
              )}
              {projectOptions.map(p => (
                <option key={p.projectId} value={p.projectId}>
                  {p.projectId === '' ? '(global)' : p.projectId}
                </option>
              ))}
            </select>
          </label>
          {mode === 'indexer' && !projectId && projectOptions.length > 0 && (
            <span className="text-xs text-amber-600">Select a project to search</span>
          )}
          <label className="flex items-center gap-2 text-sm text-gray-500">
            Limit
            <select
              value={limit}
              onChange={e => setLimit(Number(e.target.value))}
              className="border rounded-md px-2 py-1 text-sm focus:outline-none text-gray-700 bg-white"
            >
              {[5, 10, 20, 50].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        </div>
      </div>

      {/* Results */}
      {resultCount > 0 && (
        <div>
          <div className="text-xs text-gray-400 mb-3">{resultCount} result{resultCount !== 1 ? 's' : ''}</div>
          <div className="space-y-3">
            {mode === 'biblion'
              ? biblionResults.map(r => <BiblionCard key={r.id} result={r} />)
              : indexerResults.map((r, i) => <IndexerCard key={i} result={r} />)
            }
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Result Cards ───────────────────────────────────────────────────────────────

function BiblionCard({ result: r }: { result: BiblionResult }) {
  return (
    <div className="bg-white rounded-xl border shadow-sm p-4">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`px-2 py-0.5 rounded text-xs font-medium ${TYPE_COLORS[r.type] ?? 'bg-gray-100 text-gray-600'}`}>
            {r.type}
          </span>
          {r.project_id && (
            <span className="text-xs text-gray-400 font-mono">{r.project_id}</span>
          )}
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-400 shrink-0 ml-2">
          <span>score {r.score.toFixed(3)}</span>
          <span>q {r.quality.toFixed(2)}</span>
          <span>used {r.used_count}×</span>
        </div>
      </div>
      <pre className="text-xs text-gray-700 whitespace-pre-wrap font-mono bg-gray-50 rounded-lg p-3 overflow-x-auto leading-relaxed">
        {r.content.length > 600 ? r.content.slice(0, 600) + '…' : r.content}
      </pre>
      {r.tags?.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {r.tags.map(tag => (
            <span key={tag} className="px-1.5 py-0.5 bg-gray-100 text-gray-500 text-xs rounded">
              #{tag}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function IndexerCard({ result: r }: { result: IndexerResult }) {
  return (
    <div className="bg-white rounded-xl border shadow-sm p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-mono text-gray-600">
          {r.file_path}
          <span className="text-gray-400">:{r.start_line}</span>
        </span>
        <span className="text-xs text-gray-400">score {r.score.toFixed(3)}</span>
      </div>
      <pre className="text-xs text-gray-700 whitespace-pre-wrap font-mono bg-gray-50 rounded-lg p-3 overflow-x-auto leading-relaxed">
        {r.text.length > 600 ? r.text.slice(0, 600) + '…' : r.text}
      </pre>
    </div>
  )
}

// ─── BridgeTab ──────────────────────────────────────────────────────────────────

const NODE_STATUS_COLORS: Record<string, string> = {
  active:   'bg-green-100 text-green-700',
  stale:    'bg-gray-100 text-gray-500',
  inactive: 'bg-red-100 text-red-600',
}

function BridgeTab({
  bridges,
  loading,
  refreshing,
  onRefresh,
}: {
  bridges: BridgeInfo[]
  loading: boolean
  refreshing: boolean
  onRefresh: () => void
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center h-40 text-gray-400 text-sm">
        Loading…
      </div>
    )
  }

  const byProject = bridges.reduce<Record<string, BridgeInfo[]>>((acc, b) => {
    const master = b.nodes.find(n => n.role === 'master')
    const proj = master?.project_id || '(unknown)'
    acc[proj] = acc[proj] ?? []
    acc[proj].push(b)
    return acc
  }, {})

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <div className="flex gap-6 text-sm text-gray-600">
          <span>
            <span className="font-semibold text-gray-800">{bridges.length}</span> active bridge{bridges.length !== 1 ? 's' : ''}
          </span>
          <span>
            <span className="font-semibold text-gray-800">
              {bridges.reduce((s, b) => s + b.nodes.filter(n => n.role === 'friend').length, 0)}
            </span> friends connected
          </span>
        </div>
        <button
          onClick={onRefresh}
          disabled={refreshing}
          className="text-sm text-blue-600 hover:text-blue-800 disabled:opacity-40 font-medium"
        >
          {refreshing ? 'Refreshing…' : '↻ Refresh'}
        </button>
      </div>

      {bridges.length === 0 ? (
        <div className="bg-white rounded-xl border p-10 text-center text-gray-400 text-sm">
          No active bridges. Start opencode with{' '}
          <code className="bg-gray-100 px-1.5 py-0.5 rounded font-mono text-xs">--bridge master</code>{' '}
          and register via <code className="bg-gray-100 px-1.5 py-0.5 rounded font-mono text-xs">POST /bridge/set-master</code>.
        </div>
      ) : (
        <div className="space-y-6">
          {Object.entries(byProject).map(([project, bList]) => (
            <div key={project}>
              <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3 font-mono">
                {project}
              </h2>
              <div className="space-y-3">
                {bList.map(b => <BridgeCard key={b.bridgeID} bridge={b} />)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function BridgeCard({ bridge: b }: { bridge: BridgeInfo }) {
  const master = b.nodes.find(n => n.role === 'master')
  const friends = b.nodes.filter(n => n.role === 'friend')
  const now = Date.now()

  const age = master ? Math.round((now - master.heartbeat) / 1000) : null

  return (
    <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
      {/* Master row */}
      <div className="px-5 py-4 border-b bg-slate-50 flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Master</span>
            {b.masterSlug && (
              <span className="text-xs font-mono text-slate-400">{b.masterSlug}</span>
            )}
          </div>
          <div className="font-mono text-sm text-gray-800 truncate">{master?.title || b.bridgeID}</div>
          <div className="text-xs text-gray-400 font-mono mt-0.5 truncate">{master?.directory}</div>
        </div>
        <div className="flex flex-col items-end gap-1.5 shrink-0">
          <NodeStatusBadge status={master?.status ?? 'active'} />
          {age !== null && (
            <span className={`text-xs ${age > 45 ? 'text-amber-500' : 'text-gray-400'}`}>
              ♥ {age}s ago
            </span>
          )}
          <span className="text-xs text-gray-300 font-mono">{b.limit - b.nodes.length} slot{b.limit - b.nodes.length !== 1 ? 's' : ''} free</span>
        </div>
      </div>

      {/* Friends */}
      {friends.length === 0 ? (
        <div className="px-5 py-3 text-xs text-gray-300 italic">No friends connected</div>
      ) : (
        <div className="divide-y divide-gray-50">
          {friends.map(f => {
            const friendAge = Math.round((now - f.heartbeat) / 1000)
            return (
              <div key={f.nodeID} className="px-5 py-3 flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-xs font-medium text-blue-500">Friend</span>
                    {f.slug && <span className="text-xs text-gray-400 font-mono">{f.slug}</span>}
                  </div>
                  <div className="text-sm text-gray-700 truncate">{f.title || f.nodeID}</div>
                  <div className="text-xs text-gray-400 font-mono mt-0.5 truncate">{f.directory}</div>
                </div>
                <div className="flex flex-col items-end gap-1.5 shrink-0">
                  <NodeStatusBadge status={f.status} />
                  <span className={`text-xs ${friendAge > 45 ? 'text-amber-500' : 'text-gray-400'}`}>
                    ♥ {friendAge}s ago
                  </span>
                  {f.nodeURL && (
                    <span className="text-xs text-gray-300 font-mono truncate max-w-40">{f.nodeURL}</span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Bridge ID footer */}
      <div className="px-5 py-2 bg-gray-50 border-t">
        <span className="text-xs text-gray-300 font-mono">{b.bridgeID}</span>
      </div>
    </div>
  )
}

function NodeStatusBadge({ status }: { status: string }) {
  const cls = NODE_STATUS_COLORS[status] ?? 'bg-gray-100 text-gray-500'
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {status}
    </span>
  )
}
