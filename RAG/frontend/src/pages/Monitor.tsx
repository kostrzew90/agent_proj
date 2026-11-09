import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../api/client'

// ─── Types ────────────────────────────────────────────────────────────────────

interface ServiceHealth {
  ok: boolean
  name: string
  error?: string
  latency_ms?: number
  models?: string[]
}

interface Task {
  id: number
  document: string
  task_type: string
  status: string
  progress: number
  error: string | null
  created_at?: string
  completed_at?: string
}

interface MonitorData {
  stats: {
    documents: number
    chunks: number
    chat_sessions: number
    messages: number
    by_source: Record<string, number>
  }
  active_tasks: Task[]
  recent_tasks: Task[]
  services: Record<string, ServiceHealth>
}

async function fetchMonitor(): Promise<MonitorData> {
  const { data } = await apiClient.get<MonitorData>('/monitor')
  return data
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatDate(iso: string | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

const SOURCE_LABELS: Record<string, string> = {
  upload: 'Upload',
  web_crawl: 'Web crawl',
  youtube: 'YouTube',
  api: 'API',
}

const TASK_TYPE_LABELS: Record<string, string> = {
  full_pipeline: 'Document',
  crawl: 'Web crawl',
  youtube: 'YouTube transcript',
  embed: 'Re-embed',
  parse: 'Parse',
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function ServiceCard({ name, info }: { name: string; info: ServiceHealth }) {
  return (
    <div className={`card flex items-start gap-3 ${info.ok ? '' : 'border-red-700'}`}>
      <div className={`mt-0.5 h-2.5 w-2.5 rounded-full flex-shrink-0 ${info.ok ? 'bg-green-400' : 'bg-red-400'} animate-pulse`} />
      <div className="min-w-0">
        <p className="text-sm font-medium text-gray-200">{info.name || name}</p>
        {info.ok ? (
          <div className="text-xs text-gray-500 mt-0.5 space-y-0.5">
            {info.latency_ms !== undefined && <p>Latency: {info.latency_ms}ms</p>}
            {info.models && info.models.length > 0 && (
              <p className="truncate" title={info.models.join(', ')}>
                Models: {info.models.slice(0, 3).join(', ')}{info.models.length > 3 ? ` +${info.models.length - 3}` : ''}
              </p>
            )}
          </div>
        ) : (
          <p className="text-xs text-red-400 mt-0.5 truncate">{info.error}</p>
        )}
      </div>
    </div>
  )
}

function StatCard({ label, value, sub }: { label: string; value: number; sub?: string }) {
  return (
    <div className="card text-center">
      <p className="text-2xl font-bold text-gray-100">{value.toLocaleString()}</p>
      <p className="text-xs text-gray-400 mt-1">{label}</p>
      {sub && <p className="text-xs text-gray-600 mt-0.5">{sub}</p>}
    </div>
  )
}

function ProgressBar({ progress, status }: { progress: number; status: string }) {
  const pct = Math.round(progress * 100)
  const color = status === 'failed' ? 'bg-red-500' : status === 'completed' ? 'bg-green-500' : 'bg-blue-500'
  return (
    <div className="flex items-center gap-2 min-w-[80px]">
      <div className="flex-1 h-1.5 bg-gray-700 rounded-full">
        <div className={`h-1.5 rounded-full ${color} transition-all`} style={{ width: `${Math.max(pct, status === 'pending' ? 3 : pct)}%` }} />
      </div>
      <span className="text-xs text-gray-500 w-8 text-right">{pct}%</span>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    pending: 'bg-gray-700 text-gray-300',
    running: 'bg-blue-900/60 text-blue-300 animate-pulse',
    completed: 'bg-green-900/60 text-green-300',
    failed: 'bg-red-900/60 text-red-300',
  }
  return (
    <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${styles[status] || 'bg-gray-700 text-gray-400'}`}>
      {status}
    </span>
  )
}

function TaskRow({ task }: { task: Task }) {
  return (
    <tr className="border-t border-gray-700 hover:bg-gray-800/40">
      <td className="px-3 py-2 text-xs text-gray-400 w-8">{task.id}</td>
      <td className="px-3 py-2 text-sm text-gray-200 max-w-[200px]">
        <p className="truncate" title={task.document}>{task.document}</p>
        {task.error && <p className="text-xs text-red-400 truncate">{task.error}</p>}
      </td>
      <td className="px-3 py-2 text-xs text-gray-400">{TASK_TYPE_LABELS[task.task_type] ?? task.task_type}</td>
      <td className="px-3 py-2"><StatusBadge status={task.status} /></td>
      <td className="px-3 py-2"><ProgressBar progress={task.progress} status={task.status} /></td>
      <td className="px-3 py-2 text-xs text-gray-500">{formatDate(task.completed_at ?? task.created_at)}</td>
    </tr>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Monitor() {
  const { data, isLoading, error, dataUpdatedAt } = useQuery({
    queryKey: ['monitor'],
    queryFn: fetchMonitor,
    refetchInterval: 3000,
  })

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-600 border-t-blue-500" />
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="p-6 text-red-400 text-sm">Failed to load monitor data.</div>
    )
  }

  const lastUpdate = dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString('pl-PL') : '—'
  const activeCount = data.active_tasks.length

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex h-14 items-center justify-between border-b border-gray-700 px-6">
        <div className="flex items-center gap-3">
          <h1 className="text-sm font-semibold text-gray-200">System Monitor</h1>
          {activeCount > 0 && (
            <span className="flex items-center gap-1.5 rounded-full bg-blue-900/60 border border-blue-700 px-2 py-0.5 text-xs text-blue-300">
              <span className="h-1.5 w-1.5 rounded-full bg-blue-400 animate-pulse" />
              {activeCount} active
            </span>
          )}
        </div>
        <span className="text-xs text-gray-600">Updated {lastUpdate} · auto-refresh 3s</span>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6">

        {/* Services */}
        <section>
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Services</h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {Object.entries(data.services).map(([key, info]) => (
              <ServiceCard key={key} name={key} info={info} />
            ))}
          </div>
        </section>

        {/* Stats */}
        <section>
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Statistics</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard label="Documents" value={data.stats.documents}
              sub={Object.entries(data.stats.by_source).map(([k, v]) => `${SOURCE_LABELS[k] ?? k}: ${v}`).join(' · ')} />
            <StatCard label="Chunks" value={data.stats.chunks} />
            <StatCard label="Chat Sessions" value={data.stats.chat_sessions} />
            <StatCard label="Messages" value={data.stats.messages} />
          </div>
        </section>

        {/* Active Tasks */}
        <section>
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Active Tasks
            {activeCount === 0 && <span className="ml-2 text-gray-600 normal-case font-normal">— queue empty</span>}
          </h2>
          {activeCount > 0 ? (
            <div className="rounded-xl border border-gray-700 overflow-hidden">
              <table className="w-full">
                <thead className="bg-gray-800 text-xs text-gray-400">
                  <tr>
                    <th className="px-3 py-2 text-left w-8">#</th>
                    <th className="px-3 py-2 text-left">Document</th>
                    <th className="px-3 py-2 text-left">Type</th>
                    <th className="px-3 py-2 text-left">Status</th>
                    <th className="px-3 py-2 text-left">Progress</th>
                    <th className="px-3 py-2 text-left">Started</th>
                  </tr>
                </thead>
                <tbody>
                  {data.active_tasks.map(t => <TaskRow key={t.id} task={t} />)}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="rounded-xl border border-gray-700 bg-gray-800/20 py-8 text-center text-sm text-gray-600">
              No tasks running
            </div>
          )}
        </section>

        {/* Recent Tasks */}
        <section>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Recent Tasks</h2>
            <a
              href="http://localhost:5556/flower"
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
            >
              Flower UI →
            </a>
          </div>
          {data.recent_tasks.length > 0 ? (
            <div className="rounded-xl border border-gray-700 overflow-hidden">
              <table className="w-full">
                <thead className="bg-gray-800 text-xs text-gray-400">
                  <tr>
                    <th className="px-3 py-2 text-left w-8">#</th>
                    <th className="px-3 py-2 text-left">Document</th>
                    <th className="px-3 py-2 text-left">Type</th>
                    <th className="px-3 py-2 text-left">Status</th>
                    <th className="px-3 py-2 text-left">Progress</th>
                    <th className="px-3 py-2 text-left">Completed</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent_tasks.map(t => <TaskRow key={t.id} task={t} />)}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="rounded-xl border border-gray-700 bg-gray-800/20 py-6 text-center text-sm text-gray-600">
              No completed tasks yet
            </div>
          )}
        </section>

      </div>
    </div>
  )
}
