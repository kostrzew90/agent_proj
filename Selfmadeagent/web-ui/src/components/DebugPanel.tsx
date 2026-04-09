import { useState, useEffect } from 'react'
import { fetchTrace } from '../api/client'
import { MemoryView } from './MemoryView'

interface Props {
  sessionId: string | null
}

type Tab = 'trace' | 'memory'

export function DebugPanel({ sessionId }: Props) {
  const [tab, setTab] = useState<Tab>('trace')
  const [trace, setTrace] = useState<any[]>([])

  useEffect(() => {
    if (sessionId && tab === 'trace') {
      const interval = setInterval(() => {
        fetchTrace(sessionId).then(setTrace).catch(() => {})
      }, 2000)
      fetchTrace(sessionId).then(setTrace).catch(() => {})
      return () => clearInterval(interval)
    }
  }, [sessionId, tab])

  const tabClass = (t: Tab) =>
    `px-3 py-1.5 text-xs font-medium rounded-t ${tab === t ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-white'}`

  return (
    <div className="flex flex-col h-full border-l border-gray-700">
      <div className="flex border-b border-gray-700 px-2 pt-2">
        <button className={tabClass('trace')} onClick={() => setTab('trace')}>Trace</button>
        <button className={tabClass('memory')} onClick={() => setTab('memory')}>Memory</button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {tab === 'trace' && (
          <div className="p-4 space-y-2">
            {trace.map((e, i) => (
              <div key={i} className={`text-xs p-2 rounded ${
                e.outcome === 'success' ? 'bg-green-900/30 border-l-2 border-green-500' :
                e.outcome === 'blocked' ? 'bg-red-900/30 border-l-2 border-red-500' :
                e.outcome === 'warned' ? 'bg-yellow-900/30 border-l-2 border-yellow-500' :
                'bg-gray-800 border-l-2 border-gray-600'
              }`}>
                <span className="text-gray-500">{new Date(e.ts).toLocaleTimeString()}</span>
                <span className="ml-2 font-mono text-gray-300">[{e.event_type}]</span>
                <div className="mt-1 text-gray-400 break-all">{e.content?.slice(0, 200)}</div>
              </div>
            ))}
            {trace.length === 0 && <div className="text-gray-500 text-sm">No events yet</div>}
          </div>
        )}
        {tab === 'memory' && <MemoryView />}
      </div>
    </div>
  )
}
